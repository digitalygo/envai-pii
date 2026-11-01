"""Server-side chunk batching for the guardrail model adapter.

The helper is tested directly and the real `_guardrail_detect` adapter is loaded
from `app.py` with `ast`, compiled under the real source path so coverage belongs
to the shipped file. No model, Torch, Flask, or network is needed.
"""

import ast
import os
import re
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import guardrail_api
import model_batching
import pii_dictionary
import runtime_execution

APP_SRC = ROOT / "src" / "app" / "app.py"
NO_BATCH = object()


def _load_adapter(batch_size=1, lane=None):
    tree = ast.parse(APP_SRC.read_text(encoding="utf-8"))
    wanted = ("chunk_text", "_guardrail_detect", "_guardrail_detect_for_categories")
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if len(functions) != len(wanted):
        raise AssertionError("adapter guardrail non trovato in app.py")
    runtime = runtime_execution if lane is None else SimpleNamespace(MODEL_LANE=lane)
    namespace = {
        "runtime_execution": runtime,
        "model_batching": model_batching,
        "MODEL_BATCH_SIZE": batch_size,
        "MAX_WORDS": 120,
        "OVERLAP": 20,
        "re": re,
        "guardrail_api": guardrail_api,
    }
    exec(compile(ast.Module(functions, []), str(APP_SRC), "exec"), namespace)
    return namespace


class Recorder:
    def __init__(self, factory=None):
        self.calls = []
        self._factory = factory or (lambda inputs: [[] for _ in inputs])

    def __call__(self, inputs, batch_size=NO_BATCH):
        values = list(inputs)
        self.calls.append((values, batch_size))
        return self._factory(values)


def _wire(namespace, pipeline, calls):
    def complete(ents, text):
        calls["complete"].append(text)
        return ents

    def regex(text):
        calls["regex"].append(text)
        return []

    def merge(candidates, text):
        calls["merge"].append((list(candidates), text))
        return candidates

    namespace.update({
        "nlp": pipeline,
        "complete_time": complete,
        "detect_regex": regex,
        "_merge": merge,
    })


def _calls():
    return {"complete": [], "regex": [], "merge": []}


def _words(count, prefix="w"):
    return " ".join(f"{prefix}{index}" for index in range(count))


def _group_sizes(total, size):
    return [min(size, total - start) for start in range(0, total, size)]


def _first_character_rows(inputs):
    return [[{"entity_group": "FULLNAME", "start": 0, "end": 1, "score": 0.9}]
            for _ in inputs]


class ResolveBatchSizeTests(unittest.TestCase):
    def test_default_when_absent(self):
        self.assertEqual(model_batching.resolve_model_batch_size({}), 1)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(model_batching.resolve_model_batch_size(), 1)

    def test_supported_values(self):
        for raw, expected in (("1", 1), ("4", 4), ("8", 8), ("16", 16),
                              (" 4 ", 4), ("\t16\n", 16)):
            with self.subTest(raw=raw):
                self.assertEqual(
                    model_batching.resolve_model_batch_size(
                        {model_batching.BATCH_SIZE_ENV: raw}),
                    expected)

    def test_invalid_and_oversized_values_fall_back(self):
        values = ("", " ", "0", "2", "3", "5", "7", "9", "15", "32", "64",
                  "-4", "+4", "04", "4.0", "0x4", "1_6", "\u0664",
                  "quattro", "9" * 5000)
        for raw in values:
            with self.subTest(raw=raw[:20]):
                self.assertEqual(
                    model_batching.resolve_model_batch_size(
                        {model_batching.BATCH_SIZE_ENV: raw}),
                    1)

    def test_bool_like_and_non_string_values_fall_back(self):
        for raw in (True, False, None, 1, 4, 8, 16, [], {},
                    "true", "false", "True", "False", "yes", "no", "on", "off"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    model_batching.resolve_model_batch_size(
                        {model_batching.BATCH_SIZE_ENV: raw}),
                    1)

    def test_server_environment_is_read_when_no_mapping_is_given(self):
        with patch.dict(os.environ,
                        {model_batching.BATCH_SIZE_ENV: "8"}, clear=False):
            self.assertEqual(model_batching.resolve_model_batch_size(), 8)


class ChunkGroupTests(unittest.TestCase):
    def test_empty_input_has_no_group(self):
        for size in (1, 4, 8, 16):
            with self.subTest(size=size):
                self.assertEqual(list(model_batching.chunk_groups([], size)), [])

    def test_sixty_three_chunks_preserve_order_for_every_size(self):
        chunks = [f"c{index}" for index in range(63)]
        for size in (1, 4, 8, 16):
            with self.subTest(size=size):
                groups = list(model_batching.chunk_groups(chunks, size))
                self.assertEqual([len(group) for group in groups],
                                 _group_sizes(63, size))
                self.assertEqual([chunk for group in groups for chunk in group],
                                 chunks)

    def test_unsupported_size_falls_back_to_singletons(self):
        for size in (0, 2, 3, 5, 64):
            with self.subTest(size=size):
                groups = list(model_batching.chunk_groups(["a", "b"], size))
                self.assertEqual(groups, [["a"], ["b"]])


class NormalizeBatchResultTests(unittest.TestCase):
    def test_empty_rows_are_exact_and_valid(self):
        self.assertEqual(
            model_batching.normalize_batch_results([[], ()], ["a", "b"]),
            [[], []])
        self.assertEqual(model_batching.normalize_batch_results([[]], ["a"]), [[]])

    def test_entities_are_normalized_with_local_bounds(self):
        rows = model_batching.normalize_batch_results(
            [[{"entity_group": "FULLNAME", "start": 0, "end": 2, "score": 1}],
             ()],
            ["aaaa", "bbbb"])
        self.assertEqual(rows, [[{"label": "FULLNAME", "start": 0, "end": 2,
                                  "score": 1.0}], []])

    def test_tuple_of_rows_is_accepted(self):
        rows = model_batching.normalize_batch_results(([], ()), ["a", "b"])
        self.assertEqual(rows, [[], []])

    def test_missing_and_extra_rows_fail_closed(self):
        for results in ([[]], [[], [], []]):
            with self.subTest(results=results):
                with self.assertRaises(model_batching.ModelBatchResultError):
                    model_batching.normalize_batch_results(results, ["a", "b"])

    def test_flat_ambiguous_and_generator_results_fail_closed(self):
        entity = {"entity_group": "EMAIL", "start": 0, "end": 1, "score": 0.5}
        values = (
            [entity, entity],
            [entity],
            {entity["entity_group"]: entity},
            ({}, {}),
            (row for row in [[], []]),
            ([], (item for item in [])),
            ("x", "y"),
        )
        for results in values:
            with self.subTest(results=type(results).__name__):
                with self.assertRaises(model_batching.ModelBatchResultError):
                    model_batching.normalize_batch_results(results, ["a", "b"])
        with self.assertRaises(model_batching.ModelBatchResultError):
            model_batching.normalize_batch_results([entity], ["a"])

    def test_malformed_entities_fail_closed(self):
        malformed = (
            "x",
            None,
            {},
            {"entity_group": "EMAIL", "start": 0, "end": 1},
            {"entity_group": "", "start": 0, "end": 1, "score": 0.5},
            {"entity_group": 7, "start": 0, "end": 1, "score": 0.5},
            {"entity_group": "EMAIL", "start": "x", "end": 1, "score": 0.5},
            {"entity_group": "EMAIL", "start": 0, "end": 1, "score": "x"},
            {"entity_group": "EMAIL", "start": -1, "end": 1, "score": 0.5},
            {"entity_group": "EMAIL", "start": 1, "end": 1, "score": 0.5},
            {"entity_group": "EMAIL", "start": 2, "end": 1, "score": 0.5},
            {"entity_group": "EMAIL", "start": 0, "end": 4, "score": 0.5},
        )
        for entity in malformed:
            with self.subTest(entity=entity):
                with self.assertRaises(model_batching.ModelBatchResultError):
                    model_batching.normalize_batch_results([[entity]], ["abc"])

    def test_non_finite_scores_fail_closed(self):
        for score in (float("nan"), float("inf"), float("-inf"),
                      "nan", "inf", "-inf"):
            entity = {"entity_group": "EMAIL", "start": 0, "end": 1,
                      "score": score}
            with self.subTest(score=score):
                with self.assertRaises(model_batching.ModelBatchResultError):
                    model_batching.normalize_batch_results([[entity]], ["abc"])

    def test_boolean_bounds_fail_closed(self):
        for field in ("start", "end"):
            for value in (True, False):
                entity = {"entity_group": "EMAIL", "start": 0, "end": 1,
                          "score": 0.5}
                entity[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(model_batching.ModelBatchResultError):
                        model_batching.normalize_batch_results([[entity]], ["abc"])

    def test_float_bounds_never_truncate(self):
        for field, values in (("start", (0.5, 0.9, 1.0)),
                              ("end", (1.2, 1.9, 1.0))):
            for value in values:
                entity = {"entity_group": "EMAIL", "start": 0, "end": 1,
                          "score": 0.5}
                entity[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(model_batching.ModelBatchResultError):
                        model_batching.normalize_batch_results([[entity]], ["abc"])

    def test_integral_index_protocol_bounds_are_accepted(self):
        class Index:
            def __init__(self, value):
                self._value = value

            def __index__(self):
                return self._value

        entity = {"entity_group": "EMAIL", "start": Index(1),
                  "end": Index(2), "score": 0.5}
        self.assertEqual(
            model_batching.normalize_batch_results([[entity]], ["abc"]),
            [[{"label": "EMAIL", "start": 1, "end": 2, "score": 0.5}]])

    def test_span_is_checked_against_its_own_chunk(self):
        entity = {"entity_group": "EMAIL", "start": 0, "end": 4, "score": 0.5}
        with self.assertRaises(model_batching.ModelBatchResultError):
            model_batching.normalize_batch_results([[entity], []], ["abc", "abcdef"])

    def test_error_message_never_contains_document_values(self):
        secret = "SECRET-DOC-VALUE"
        entity = {"entity_group": secret, "start": secret, "end": 1, "score": 0.5}
        with self.assertRaises(model_batching.ModelBatchResultError) as caught:
            model_batching.normalize_batch_results([[entity]], ["abc"])
        self.assertEqual(str(caught.exception), model_batching.RESULT_ERROR_MESSAGE)
        self.assertNotIn(secret, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)


class AdapterBatchShapeTests(unittest.TestCase):
    def test_sixty_three_chunks_for_every_configured_size(self):
        text = _words(6252)
        for size in (1, 4, 8, 16):
            with self.subTest(size=size):
                namespace = _load_adapter(size)
                pipeline = Recorder()
                calls = _calls()
                _wire(namespace, pipeline, calls)
                out = namespace["_guardrail_detect"](text, lambda: None)
                chunks = namespace["chunk_text"](text)
                self.assertEqual(out, [])
                self.assertEqual(len(chunks), 63)
                self.assertEqual(len(chunks[-1][0].split()), 52)
                self.assertEqual([len(inputs) for inputs, _batch in pipeline.calls],
                                 _group_sizes(63, size))
                self.assertEqual(
                    [chunk for inputs, _batch in pipeline.calls for chunk in inputs],
                    [chunk for chunk, _offset in chunks])
                for _inputs, batch in pipeline.calls:
                    if size == 1:
                        self.assertIs(batch, NO_BATCH)
                    else:
                        self.assertEqual(batch, size)
                self.assertEqual(calls["complete"], [text])
                self.assertEqual(calls["regex"], [text])
                self.assertEqual(calls["merge"], [([], text)])

    def test_batch_one_keeps_flat_and_dict_results(self):
        entity = {"entity_group": "EMAIL", "start": 0, "end": 1, "score": 0.5}
        for result in (entity, [entity], [[entity]]):
            with self.subTest(result=result):
                namespace = _load_adapter(1)
                pipeline = Recorder(lambda _inputs: result)
                calls = _calls()
                _wire(namespace, pipeline, calls)
                out = namespace["_guardrail_detect"]("x", lambda: None)
                self.assertEqual([(item["label"], item["start"], item["end"])
                                  for item in out],
                                 [("EMAIL", 0, 1)])
                self.assertIs(pipeline.calls[0][1], NO_BATCH)

    def test_batch_one_deadline_event_order_is_unchanged(self):
        lane = runtime_execution.NativeExecutionLane("model-batching-b1-order")
        events = []
        try:
            namespace = _load_adapter(1, lane=lane)

            def pipeline(inputs):
                events.append("nlp")
                return [[] for _ in inputs]

            _wire(namespace, Recorder(pipeline), _calls())

            def check():
                events.append("check")
                if "nlp" in events:
                    raise RuntimeError("deadline")

            with self.assertRaises(RuntimeError):
                namespace["_guardrail_detect"]("x", check)
        finally:
            lane.shutdown()
        self.assertEqual(events, ["check", "check", "nlp", "check"])


class AdapterOffsetTests(unittest.TestCase):
    def test_unicode_and_overlap_offsets_are_global_and_in_order(self):
        text = _words(130, prefix="città") + " Mario Rossi"
        namespace = _load_adapter(4)
        pipeline = Recorder(_first_character_rows)
        calls = _calls()
        _wire(namespace, pipeline, calls)
        out = namespace["_guardrail_detect"](text, lambda: None)
        chunks = namespace["chunk_text"](text)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(out), 2)
        self.assertEqual([(entity["start"], entity["end"]) for entity in out],
                         [(offset, offset + 1) for _chunk, offset in chunks])
        for entity, (chunk, _offset) in zip(out, chunks):
            self.assertEqual(text[entity["start"]:entity["end"]], chunk[0])
        self.assertLess(chunks[1][1], chunks[0][1] + len(chunks[0][0]))
        self.assertEqual(pipeline.calls[0][1], 4)


class AdapterEmptyInputTests(unittest.TestCase):
    def test_empty_text_never_calls_the_model(self):
        for size in (1, 4):
            with self.subTest(size=size):
                namespace = _load_adapter(size)
                pipeline = Recorder()
                calls = _calls()
                _wire(namespace, pipeline, calls)
                self.assertEqual(
                    namespace["_guardrail_detect"]("   ", lambda: None), [])
                self.assertEqual(pipeline.calls, [])
                self.assertEqual(calls["complete"], ["   "])
                self.assertEqual(calls["regex"], ["   "])
                self.assertEqual(calls["merge"], [([], "   ")])

    def test_empty_row_for_a_non_empty_chunk_is_valid(self):
        namespace = _load_adapter(4)
        pipeline = Recorder()
        calls = _calls()
        _wire(namespace, pipeline, calls)
        self.assertEqual(namespace["_guardrail_detect"]("solo", lambda: None), [])
        self.assertEqual(pipeline.calls, [(["solo"], 4)])
        self.assertEqual(calls["complete"], ["solo"])
        self.assertEqual(calls["regex"], ["solo"])
        self.assertEqual(calls["merge"], [([], "solo")])


class AdapterFailClosedTests(unittest.TestCase):
    def test_invalid_batch_results_never_reach_regex_or_merge(self):
        text = _words(125)
        entity = {"entity_group": "EMAIL", "start": 0, "end": 1, "score": 0.5}
        results = (
            [[]],
            [[], [], []],
            [entity, entity],
            [{}, {}],
            (row for row in [[], []]),
            ("x", "y"),
            (["x"], []),
        )
        for result in results:
            with self.subTest(result=type(result).__name__):
                namespace = _load_adapter(4)
                pipeline = Recorder(lambda _inputs, value=result: value)
                calls = _calls()
                _wire(namespace, pipeline, calls)
                with self.assertRaises(model_batching.ModelBatchResultError):
                    namespace["_guardrail_detect"](text, lambda: None)
                self.assertEqual(len(pipeline.calls), 1)
                self.assertEqual(calls["complete"], [])
                self.assertEqual(calls["regex"], [])
                self.assertEqual(calls["merge"], [])

    def test_invalid_local_span_fails_the_whole_group(self):
        text = _words(125)
        bad = {"entity_group": "EMAIL", "start": 0, "end": 10 ** 6, "score": 0.5}
        namespace = _load_adapter(4)
        pipeline = Recorder(lambda inputs: [[bad] for _ in inputs])
        calls = _calls()
        _wire(namespace, pipeline, calls)
        with self.assertRaises(model_batching.ModelBatchResultError):
            namespace["_guardrail_detect"](text, lambda: None)
        self.assertEqual(calls["regex"], [])
        self.assertEqual(calls["merge"], [])


class AdapterDeadlineTests(unittest.TestCase):
    def test_deadline_before_the_batch_prevents_the_model_call(self):
        namespace = _load_adapter(4)
        pipeline = Recorder()
        calls = _calls()
        _wire(namespace, pipeline, calls)

        def check():
            raise RuntimeError("deadline")

        with self.assertRaises(RuntimeError):
            namespace["_guardrail_detect"](_words(125), check)
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(calls["regex"], [])
        self.assertEqual(calls["merge"], [])

    def test_deadline_after_the_batch_is_checked_by_the_lane(self):
        lane = runtime_execution.NativeExecutionLane("model-batching-after")
        events = []
        try:
            namespace = _load_adapter(4, lane=lane)

            def pipeline(inputs):
                events.append("nlp")
                return [[] for _ in inputs]

            pipeline_recorder = Recorder(pipeline)
            _wire(namespace, pipeline_recorder, _calls())

            def check():
                events.append("check")
                if "nlp" in events:
                    raise RuntimeError("deadline")

            with self.assertRaises(RuntimeError):
                namespace["_guardrail_detect"](_words(125), check)
        finally:
            lane.shutdown()
        self.assertEqual(events, ["check", "check", "nlp", "check"])
        self.assertEqual(len(pipeline_recorder.calls), 1)

    def test_waiting_on_the_native_lane_still_checks_the_deadline(self):
        lane = runtime_execution.NativeExecutionLane("model-batching-wait")
        started = threading.Event()
        release = threading.Event()
        holder_errors = []

        def hold_lane():
            started.set()
            if not release.wait(2):
                raise RuntimeError("hold timeout")

        def hold():
            try:
                lane.run(hold_lane)
            except BaseException as exc:
                holder_errors.append(exc)

        thread = threading.Thread(target=hold)
        thread.start()
        try:
            self.assertTrue(started.wait(1))
            namespace = _load_adapter(4, lane=lane)
            pipeline = Recorder()
            calls = _calls()
            _wire(namespace, pipeline, calls)
            checks = []

            def check():
                checks.append(1)
                if len(checks) == 2:
                    raise RuntimeError("deadline while waiting")

            with self.assertRaises(RuntimeError):
                namespace["_guardrail_detect"](_words(125), check)
            self.assertEqual(pipeline.calls, [])
            self.assertEqual(calls["regex"], [])
        finally:
            release.set()
            thread.join(timeout=2)
            lane.shutdown()
        self.assertFalse(thread.is_alive())
        self.assertEqual(holder_errors, [])

    def test_model_unavailable_is_raised_before_batching(self):
        namespace = _load_adapter(4)
        pipeline = Recorder()
        calls = _calls()
        _wire(namespace, pipeline, calls)
        namespace["nlp"] = None
        with self.assertRaises(guardrail_api.ModelUnavailable):
            namespace["_guardrail_detect"](_words(125), lambda: None)
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(calls["regex"], [])


class AdapterIsolationTests(unittest.TestCase):
    def test_category_binders_keep_their_own_filter_and_batch(self):
        text = "Mario x@y.it"
        rows = [{"entity_group": "FULLNAME", "start": 0, "end": 5, "score": 0.9},
                {"entity_group": "EMAIL", "start": 6, "end": 12, "score": 0.8}]

        def factory(inputs):
            return [rows for _ in inputs]

        for categories, expected in ((("FULLNAME",), ["FULLNAME"]),
                                     (("EMAIL",), ["EMAIL"])):
            with self.subTest(categories=categories):
                namespace = _load_adapter(4)
                pipeline = Recorder(factory)
                calls = _calls()
                _wire(namespace, pipeline, calls)
                detect = namespace["_guardrail_detect_for_categories"](categories)
                out = detect(text, lambda: None)
                self.assertEqual(calls["merge"], [(calls["merge"][0][0], text)])
                self.assertEqual([item["label"] for item in calls["merge"][0][0]],
                                 expected)
                self.assertEqual(pipeline.calls, [([text], 4)])
                self.assertEqual([item["label"] for item in out], expected)

    def test_seed_protected_gaps_never_share_a_batch(self):
        tags = ("FULLNAME", "EMAIL")
        parsed = pii_dictionary.parse_seed({"[FULLNAME_9]": "Mario Rossi"}, tags)
        text = (_words(5, prefix="prima") + " Mario Rossi "
                + _words(5, prefix="dopo"))
        namespace = _load_adapter(4)
        pipeline = Recorder()
        calls = _calls()
        _wire(namespace, pipeline, calls)
        out = pii_dictionary.anonymize(
            text, parsed, tags, detect=namespace["_guardrail_detect"],
            check_deadline=lambda: None)
        self.assertEqual(len(pipeline.calls), 2)
        for inputs, batch in pipeline.calls:
            self.assertEqual(len(inputs), 1)
            self.assertEqual(batch, 4)
            self.assertNotIn("Mario Rossi", " ".join(inputs))
        self.assertEqual(out["anonymized_text"].count("[FULLNAME_9]"), 1)
        self.assertEqual(out["dictionary_delta"], {})

    def test_separate_invocations_never_accumulate_inputs(self):
        namespace = _load_adapter(4)
        pipeline = Recorder()
        calls = _calls()
        _wire(namespace, pipeline, calls)
        detect = namespace["_guardrail_detect"]
        detect("alpha beta", lambda: None)
        detect("gamma delta epsilon", lambda: None)
        self.assertEqual([inputs for inputs, _batch in pipeline.calls],
                         [["alpha beta"], ["gamma delta epsilon"]])
        self.assertEqual([batch for _inputs, batch in pipeline.calls], [4, 4])


class StartupResolutionTests(unittest.TestCase):
    def test_app_resolves_the_server_batch_size_once_at_startup(self):
        tree = ast.parse(APP_SRC.read_text(encoding="utf-8"))
        assignments = [
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name)
                    and target.id == "MODEL_BATCH_SIZE"
                    for target in node.targets)
        ]
        self.assertEqual(len(assignments), 1)
        value = assignments[0].value
        self.assertIsInstance(value, ast.Call)
        self.assertEqual(ast.unparse(value),
                         "model_batching.resolve_model_batch_size()")


if __name__ == "__main__":
    unittest.main()
