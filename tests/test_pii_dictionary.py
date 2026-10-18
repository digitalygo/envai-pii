# -*- coding: utf-8 -*-
"""Motore del dizionario seed (`src/app/pii_dictionary.py`), senza Flask ne' modello.

Verifica la parte di contratto ENVAS-23 che vive fuori dall'HTTP: normalizzazione
con offset per le espansioni casefold, validazione del seed, localizzazione delle
PII note anche quando il rilevatore non le vede, protezione dei placeholder,
fusione nei soli tratti non protetti, allocazione degli ID e delta.

Solo standard library: gira dove il contratto dice (CI senza install).
Tutti i valori sono SINTETICI.
"""

import sys
import tracemalloc
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import guardrail_limits  # noqa: E402
import pii_dictionary as pd  # noqa: E402

TAGS = ["FULLNAME", "EMAIL", "CITY", "ORG", "ID_DOC", "DATE", "STREET", "PROVINCE",
        "GENDER"]


def seed(pairs):
    return pd.parse_seed(pairs, TAGS)


def ent(label, start, end, score=0.9):
    return {"label": label, "start": start, "end": end, "score": score,
            "validated": False, "source": "modello"}


def detect_literals(*specs):
    """Rilevatore finto: (testo, label) cercati letteralmente, offset locali."""
    def detect(text, _check):
        out = []
        for literal, label in specs:
            position = 0
            while True:
                found = text.find(literal, position)
                if found < 0:
                    break
                out.append(ent(label, found, found + len(literal)))
                position = found + 1
        return out
    return detect


class Normalizzazione(unittest.TestCase):
    def test_casefold_e_spazi(self):
        self.assertEqual(pd.normalize("  Mario   Rossi "), "mario rossi")
        self.assertEqual(pd.normalize("Straße"), "strasse")
        self.assertEqual(pd.normalize("STRASSE"), "strasse")
        self.assertEqual(pd.normalize("Mario\n\tRossi"), "mario rossi")

    def test_accenti_e_punteggiatura_restano_significativi(self):
        self.assertNotEqual(pd.normalize("Rossi"), pd.normalize("Ròssi"))
        self.assertNotEqual(pd.normalize("a.b"), pd.normalize("ab"))


class ValidazioneSeed(unittest.TestCase):
    def test_chiavi_canoniche(self):
        self.assertEqual(pd.parse_placeholder("[ID_DOC_12]", set(TAGS)), ("ID_DOC", 12))
        self.assertEqual(pd.parse_placeholder("[FULLNAME_999999999]", set(TAGS)),
                         ("FULLNAME", 999999999))

    def test_chiavi_non_canoniche(self):
        for key in ("FULLNAME_1", "[FULLNAME_01]", "[FULLNAME_0]", "[FULLNAME_1000000000]",
                    "[OTHER_1]", "[fullname_1]", "[FULLNAME_1]x", "[FULLNAME_]",
                    "[FULLNAME__1]", "[FULLNAME_1 ]", "[FULLNAME-1]", "[[FULLNAME_1]]",
                    "[FULLNAME_1", "FULLNAME_1]", "[FULLNAME_\u0661]"):
            self.assertIsNone(pd.parse_placeholder(key, set(TAGS)), key)

    def test_dizionario_non_oggetto(self):
        for value in (None, [], "x", 5, True):
            with self.assertRaises(pd.InvalidSeed):
                pd.parse_seed(value, TAGS)

    def test_chiave_non_stringa(self):
        self.assertIsNone(pd.parse_placeholder(123, set(TAGS)))
        self.assertIsNone(pd.parse_placeholder(None, set(TAGS)))

    def test_valori_non_stringa_o_vuoti(self):
        for value in (1, None, True, [], "", "   ", "\t\n"):
            with self.assertRaises(pd.InvalidSeed):
                pd.parse_seed({"[FULLNAME_1]": value}, TAGS)

    def test_originali_uguali_dopo_normalizzazione_confliggono(self):
        with self.assertRaises(pd.SeedConflict):
            pd.parse_seed({"[FULLNAME_1]": "Mario Rossi",
                           "[CITY_1]": "mario   rossi"}, TAGS)
        with self.assertRaises(pd.SeedConflict):
            pd.parse_seed({"[FULLNAME_1]": "Rossi", "[FULLNAME_2]": "ROSSI"}, TAGS)

    def test_accenti_non_confliggono(self):
        parsed = pd.parse_seed({"[FULLNAME_1]": "Rossi", "[FULLNAME_2]": "Ròssi"}, TAGS)
        self.assertEqual(len(parsed.pairs), 2)

    def test_limite_voci(self):
        massimo = {"[FULLNAME_%d]" % i: "valore-%d" % i for i in range(1, 257)}
        self.assertEqual(len(pd.parse_seed(massimo, TAGS).pairs), 256)
        troppe = dict(massimo)
        troppe["[FULLNAME_257]"] = "valore-257"
        with self.assertRaises(pd.PayloadTooLarge):
            pd.parse_seed(troppe, TAGS)

    def test_limiti_espliciti_permettono_seed_sopra_256(self):
        dictionary = {"[FULLNAME_%d]" % index: "synthetic-%d" % index
                      for index in range(1, 301)}
        with self.assertRaises(pd.PayloadTooLarge):
            pd.parse_seed(dictionary, TAGS)
        limits = guardrail_limits.RequestLimits(300, 4096, 1048576, 8388608)
        self.assertEqual(len(pd.parse_seed(dictionary, TAGS, limits=limits).pairs), 300)

    def test_limite_singolo_originale(self):
        ok = pd.parse_seed({"[FULLNAME_1]": "a" * 4096}, TAGS)
        self.assertEqual(len(ok.pairs[0][3]), 4096)
        with self.assertRaises(pd.PayloadTooLarge):
            pd.parse_seed({"[FULLNAME_1]": "a" * 4097}, TAGS)

    def test_limite_aggregato(self):
        # 16 x 4096 = 65536 esatti, valori distinti per non creare conflitti.
        valori = {"[FULLNAME_%d]" % (i + 1): ("x" * 4095) + chr(0x4E00 + i)
                  for i in range(16)}
        self.assertEqual(len(pd.parse_seed(valori, TAGS).pairs), 16)
        valori["[FULLNAME_17]"] = "z"
        with self.assertRaises(pd.PayloadTooLarge):
            pd.parse_seed(valori, TAGS)

    def test_seed_immutabile_e_copiato(self):
        sorgente = {"[FULLNAME_1]": "Mario Rossi"}
        parsed = pd.parse_seed(sorgente, TAGS)
        sorgente["[FULLNAME_1]"] = "Alterato"
        sorgente["[EMAIL_1]"] = "x@y.it"
        self.assertEqual(parsed.pairs,
                         (("[FULLNAME_1]", "FULLNAME", 1, "Mario Rossi"),))
        self.assertEqual(parsed.reserved_ids(), {"FULLNAME": 1})
        self.assertEqual(parsed.lookup("FULLNAME", "mario rossi"), "[FULLNAME_1]")
        self.assertEqual(parsed.lookup("EMAIL", "mario rossi"), "[FULLNAME_1]")


class RicercaPlaceholder(unittest.TestCase):
    def test_solo_canonici_con_label_note(self):
        testo = "[FULLNAME_1] [fullname_1] [FULLNAME_01] [OTHER_1] [ID_DOC_42]"
        trovati = pd.find_placeholders(testo, TAGS)
        self.assertEqual([(label, index) for _s, _e, label, index in trovati],
                         [("FULLNAME", 1), ("ID_DOC", 42)])
        self.assertEqual(pd.count_placeholders(testo, TAGS), 2)

    def test_conteggio_con_ripetizioni(self):
        self.assertEqual(pd.count_placeholders("[EMAIL_1] e [EMAIL_1]", TAGS), 2)
        self.assertEqual(pd.count_placeholders("niente", TAGS), 0)


class Localizzazione(unittest.TestCase):
    def test_originale_noto_mascherato_anche_senza_modello(self):
        parsed = seed({"[FULLNAME_1]": "Mario Rossi"})
        out = pd.anonymize("Mario Rossi abita a Milano.", parsed, TAGS)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1] abita a Milano.")
        self.assertEqual(out["dictionary_delta"], {})
        self.assertEqual(out["placeholder_count"], 1)

    def test_casefold_su_espansione_intera(self):
        out = pd.anonymize("Die Straße ist frei.", seed({"[STREET_1]": "STRASSE"}), TAGS)
        self.assertEqual(out["anonymized_text"], "Die [STREET_1] ist frei.")

    def test_mai_mezzo_carattere_espanso(self):
        out = pd.anonymize("ß", seed({"[STREET_1]": "s"}), TAGS)
        self.assertEqual(out["anonymized_text"], "ß")
        self.assertEqual(out["dictionary_delta"], {})
        # "ss" invece copre l'intera espansione
        out2 = pd.anonymize("ß", seed({"[STREET_1]": "ss"}), TAGS)
        self.assertEqual(out2["anonymized_text"], "[STREET_1]")

    def test_confini_di_parola(self):
        parsed = seed({"[FULLNAME_1]": "DE"})
        out = pd.anonymize("CORDELLA e DE.", parsed, TAGS)
        self.assertIn("CORDELLA", out["anonymized_text"])
        self.assertEqual(out["anonymized_text"], "CORDELLA e [FULLNAME_1].")
        out2 = pd.anonymize("Rossi", seed({"[FULLNAME_1]": "Ro"}), TAGS)
        self.assertEqual(out2["anonymized_text"], "Rossi")

    def test_punteggiatura_letterale(self):
        parsed = seed({"[EMAIL_1]": "a.b+c@x.it"})
        out = pd.anonymize("scrivi a a.b+c@x.it ora", parsed, TAGS)
        self.assertEqual(out["anonymized_text"], "scrivi a [EMAIL_1] ora")

    def test_spazi_varianti(self):
        out = pd.anonymize("Mario\n   Rossi qui", seed({"[FULLNAME_1]": "Mario Rossi"}), TAGS)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1] qui")
        out2 = pd.anonymize("Mario Rossi qui", seed({"[FULLNAME_1]": "Mario   Rossi"}), TAGS)
        self.assertEqual(out2["anonymized_text"], "[FULLNAME_1] qui")

    def test_piu_lungo_vince(self):
        parsed = seed({"[FULLNAME_1]": "Mario Rossi", "[FULLNAME_2]": "Rossi"})
        out = pd.anonymize("Mario Rossi", parsed, TAGS)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1]")

    def test_candidato_corto_sopravvive_al_match_lungo_occupato(self):
        testo = "A B C D        E"
        parsed = seed({
            "[FULLNAME_1]": "A B C D",
            "[CITY_1]": "A B",
            "[ORG_1]": "C D E",
        })
        out = pd.anonymize(testo, parsed, TAGS)
        # C D E has fewer normalized characters than A B C D, but its original
        # span is longer due to whitespace. Once it wins, A B remains eligible.
        self.assertEqual(out["anonymized_text"], "[CITY_1] [ORG_1]")

    def test_tie_lessicale_e_indipendenza_dall_ordine(self):
        a = {"[ORG_1]": "cd ef", "[CITY_1]": "ab cd"}
        b = {"[CITY_1]": "ab cd", "[ORG_1]": "cd ef"}
        out_a = pd.anonymize("ab cd ef", pd.parse_seed(a, TAGS), TAGS)
        out_b = pd.anonymize("ab cd ef", pd.parse_seed(b, TAGS), TAGS)
        self.assertEqual(out_a["anonymized_text"], "[CITY_1] ef")
        self.assertEqual(out_a, out_b)

    def test_placeholder_esistente_intoccato(self):
        out = pd.anonymize("[FULLNAME_9] Mario Rossi",
                           seed({"[FULLNAME_1]": "Mario Rossi"}), TAGS)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_9] [FULLNAME_1]")
        self.assertEqual(out["placeholder_count"], 2)

    def test_seed_che_punta_a_un_placeholder_non_riscrive(self):
        out = pd.anonymize("contatta [EMAIL_5] ora", seed({"[FULLNAME_1]": "[EMAIL_5]"}), TAGS)
        self.assertEqual(out["anonymized_text"], "contatta [EMAIL_5] ora")
        self.assertEqual(out["dictionary_delta"], {})
        self.assertEqual(out["placeholder_count"], 1)

    def test_sostituzione_a_passo_unico_niente_riscansione(self):
        visti = []

        def rec(text, _check):
            visti.append(text)
            return [ent("EMAIL", 0, min(4, len(text)))] if text else []

        out = pd.anonymize("Mario", seed({"[FULLNAME_1]": "Mario"}), TAGS, detect=rec)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1]")
        self.assertNotIn("[FULLNAME_1]", "".join(visti))

    def test_il_rilevatore_gira_solo_sui_tratti_non_protetti(self):
        chiamate = []

        def rec(text, _check):
            chiamate.append(text)
            return []

        out = pd.anonymize("Mario Rossi e Roma",
                           seed({"[FULLNAME_1]": "Mario Rossi"}), TAGS, detect=rec)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1] e Roma")
        self.assertTrue(any("Roma" in call for call in chiamate))
        self.assertFalse(any("Mario" in call for call in chiamate))

    def test_seed_ripetuto_nel_testo(self):
        out = pd.anonymize("Mario Rossi e Mario Rossi",
                           seed({"[FULLNAME_1]": "Mario Rossi"}), TAGS)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1] e [FULLNAME_1]")
        self.assertEqual(out["dictionary_delta"], {})
        self.assertEqual(out["placeholder_count"], 2)

    def test_entita_malformate_scartate(self):
        def detect(_text, _check):
            return [{"label": "FULLNAME"},                       # senza start/end
                    {"label": "FULLNAME", "start": "x", "end": 1},
                    {"label": "FULLNAME", "start": 3, "end": 2},   # end <= start
                    {"label": "FULLNAME", "start": 0, "end": 999},  # fuori dal tratto
                    {"label": "FULLNAME", "start": 0, "end": 5}]

        out = pd.anonymize("Mario", pd.parse_seed({}, TAGS), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1]")
        self.assertEqual(out["dictionary_delta"], {"[FULLNAME_1]": "Mario"})

    def test_sovrapposizioni_tra_entita_rilevate(self):
        def detect(_text, _check):
            return [ent("FULLNAME", 0, 10), ent("CITY", 0, 5)]

        out = pd.anonymize("Mario Ross", pd.parse_seed({}, TAGS), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1]")
        self.assertEqual(out["dictionary_delta"], {"[FULLNAME_1]": "Mario Ross"})

    def test_frammento_del_rilevatore_fuori_dal_tratto_scartato(self):
        def evil(_text, _check):
            return [ent("FULLNAME", -3, 5)]

        out = pd.anonymize("Mario Rossi", seed({"[FULLNAME_7]": "Mario Rossi"}),
                           TAGS, detect=evil)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_7]")


class Allocazione(unittest.TestCase):
    def test_id_in_ordine_di_incontro(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("Rossi", "FULLNAME"))
        out = pd.anonymize("Mario e Rossi", pd.parse_seed({}, TAGS), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1] e [FULLNAME_2]")
        self.assertEqual(out["dictionary_delta"],
                         {"[FULLNAME_1]": "Mario", "[FULLNAME_2]": "Rossi"})

    def test_ripetizione_normalizzata_stesso_placeholder(self):
        detect = detect_literals(("MARIO", "FULLNAME"), ("mario", "FULLNAME"))
        out = pd.anonymize("MARIO e mario", pd.parse_seed({}, TAGS), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1] e [FULLNAME_1]")
        self.assertEqual(out["dictionary_delta"], {"[FULLNAME_1]": "MARIO"})
        self.assertEqual(out["placeholder_count"], 2)

    def test_id_parte_sopra_le_chiavi_del_seed(self):
        out = pd.anonymize("scrivi a info@x.it", seed({"[EMAIL_5]": "a@b.it"}),
                           TAGS, detect=detect_literals(("info@x.it", "EMAIL")))
        self.assertEqual(out["anonymized_text"], "scrivi a [EMAIL_6]")
        self.assertEqual(out["dictionary_delta"], {"[EMAIL_6]": "info@x.it"})

    def test_id_parte_sopra_i_placeholder_nel_testo(self):
        out = pd.anonymize("[FULLNAME_7] e Mario Rossi", pd.parse_seed({}, TAGS), TAGS,
                           detect=detect_literals(("Mario Rossi", "FULLNAME")))
        self.assertEqual(out["anonymized_text"], "[FULLNAME_7] e [FULLNAME_8]")

    def test_label_sconosciute_scartate(self):
        def detect(_text, _check):
            return [ent("OTHER", 0, 4)]

        out = pd.anonymize("test", pd.parse_seed({}, TAGS), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], "test")
        self.assertEqual(out["dictionary_delta"], {})

    def test_tag_con_underscore(self):
        out = pd.anonymize("AB123CD", pd.parse_seed({}, TAGS), TAGS,
                           detect=detect_literals(("AB123CD", "ID_DOC")))
        self.assertEqual(out["anonymized_text"], "[ID_DOC_1]")
        self.assertEqual(out["dictionary_delta"], {"[ID_DOC_1]": "AB123CD"})

    def test_valore_rilevato_che_combacia_col_seed_riusa_la_chiave(self):
        # il rilevatore restituisce "Rossi" dentro "RossiX": il confine manca, ma
        # l'identita' normalizzata combacia col seed e la chiave va riusata.
        def detect(_text, _check):
            return [ent("FULLNAME", 0, 5)]

        out = pd.anonymize("RossiX", seed({"[FULLNAME_7]": "Rossi"}), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_7]X")
        self.assertEqual(out["dictionary_delta"], {})

    def test_esaurimento_id(self):
        parsed = seed({"[EMAIL_999999999]": "a@b.it"})
        with self.assertRaises(pd.AllocationExhausted):
            pd.anonymize("scrivi a x@y.it", parsed, TAGS,
                         detect=detect_literals(("x@y.it", "EMAIL")))

    def test_id_massimo_occupato_dal_seed_non_esaurisce_senza_nuove_allocazioni(self):
        parsed = seed({"[FULLNAME_999999999]": "Mario Rossi"})
        out = pd.anonymize("Mario Rossi", parsed, TAGS)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_999999999]")
        self.assertEqual(out["dictionary_delta"], {})

    def test_esaurimento_id_da_placeholder_nel_testo(self):
        with self.assertRaises(pd.AllocationExhausted):
            pd.anonymize("[EMAIL_999999999] e x@y.it", pd.parse_seed({}, TAGS), TAGS,
                         detect=detect_literals(("x@y.it", "EMAIL")))

    def test_limite_testo(self):
        vuoto = pd.parse_seed({}, TAGS)
        out = pd.anonymize("a" * 100000, vuoto, TAGS)
        self.assertEqual(len(out["anonymized_text"]), 100000)
        with self.assertRaises(pd.PayloadTooLarge):
            pd.anonymize("a" * 100001, vuoto, TAGS)

    def test_testo_non_stringa(self):
        with self.assertRaises(TypeError):
            pd.anonymize(123, pd.parse_seed({}, TAGS), TAGS)


class BatchStatoCondiviso(unittest.TestCase):
    """`anonymize_batch`: una sola mappa di lavoro per l'intera richiesta.

    La numerazione dei nuovi ID e' riservata su TUTTI gli input prima di
    qualunque allocazione; una coppia allocata in un input e' un match noto
    letterale negli input successivi anche se il rilevatore non la vede.
    """

    def test_riuso_cross_input_e_delta_aggregato(self):
        calls = []

        def detect(text, _check):
            calls.append(text)
            if len(calls) > 1:
                return []          # il modello "dimentica" gli input successivi
            out = []
            for literal, label in (("Mario Rossi", "FULLNAME"),
                                   ("mario.rossi@example.com", "EMAIL")):
                position = text.find(literal)
                if position >= 0:
                    out.append(ent(label, position, position + len(literal)))
            return out

        inputs = [("file_1", "Mario Rossi scrive a mario.rossi@example.com"),
                  ("file_2", "Conferma per Mario Rossi: mario.rossi@example.com"),
                  ("text", "Referente Mario Rossi")]
        results, delta = pd.anonymize_batch(inputs, seed({}), TAGS, detect=detect)
        self.assertEqual([input_id for input_id, _out in results],
                         ["file_1", "file_2", "text"])
        self.assertEqual(results[0][1]["anonymized_text"],
                         "[FULLNAME_1] scrive a [EMAIL_1]")
        self.assertEqual(results[1][1]["anonymized_text"],
                         "Conferma per [FULLNAME_1]: [EMAIL_1]")
        self.assertEqual(results[2][1]["anonymized_text"], "Referente [FULLNAME_1]")
        self.assertEqual(delta, {"[FULLNAME_1]": "Mario Rossi",
                                 "[EMAIL_1]": "mario.rossi@example.com"})
        self.assertGreaterEqual(len(calls), 2)

    def test_id_riservati_su_tutti_gli_input_prima_di_allocare(self):
        def detect(text, _check):
            position = text.find("x@y.it")
            return [ent("EMAIL", position, position + 6)] if position >= 0 else []

        inputs = [("file_1", "scrivi a x@y.it"),
                  ("file_2", "placeholder [EMAIL_9]")]
        results, delta = pd.anonymize_batch(inputs, seed({}), TAGS, detect=detect)
        self.assertEqual(results[0][1]["anonymized_text"], "scrivi a [EMAIL_10]")
        self.assertEqual(results[1][1]["anonymized_text"], "placeholder [EMAIL_9]")
        self.assertEqual(delta, {"[EMAIL_10]": "x@y.it"})

    def test_categorie_diverse_stesso_originale_riusano_primo_binding(self):
        def detect(text, _check):
            first = text.find("Rossi")
            second = text.find("ROSSI")
            return [ent("FULLNAME", first, first + 5),
                    ent("CITY", second, second + 5)]

        results, delta = pd.anonymize_batch([("text", "Rossi e ROSSI")],
                                            seed({}), TAGS, detect=detect)
        self.assertEqual(results[0][1]["anonymized_text"],
                         "[FULLNAME_1] e [FULLNAME_1]")
        self.assertEqual(delta, {"[FULLNAME_1]": "Rossi"})
        restored_seed = seed(delta)
        restored = pd.anonymize(
            results[0][1]["anonymized_text"], restored_seed, TAGS)
        self.assertEqual(restored["anonymized_text"],
                         "[FULLNAME_1] e [FULLNAME_1]")
        self.assertEqual(restored["dictionary_delta"], {})

    def test_primo_binding_segue_l_ordine_inverso_delle_occorrenze(self):
        detect = detect_literals(("ROSSI", "CITY"), ("Rossi", "FULLNAME"))
        out = pd.anonymize("ROSSI e Rossi", seed({}), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], "[CITY_1] e [CITY_1]")
        self.assertEqual(out["dictionary_delta"], {"[CITY_1]": "ROSSI"})

    def test_identita_globale_unicode_riusa_la_prima_forma(self):
        detect = detect_literals(("Straße", "FULLNAME"), ("STRASSE", "CITY"))
        out = pd.anonymize("Straße und STRASSE", seed({}), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1] und [FULLNAME_1]")
        self.assertEqual(out["dictionary_delta"], {"[FULLNAME_1]": "Straße"})

    def test_entita_normalizzata_vuota_non_crea_delta(self):
        def detect(_text, _check):
            return [ent("FULLNAME", 0, 2)]

        out = pd.anonymize(" \tX", seed({}), TAGS, detect=detect)
        self.assertEqual(out["anonymized_text"], " \tX")
        self.assertEqual(out["dictionary_delta"], {})

    def test_oltre_256_nuove_coppie_fuori_dai_limiti_del_seed(self):
        values = ["v%03d" % index for index in range(300)]
        text = " | ".join(values)

        def detect(text, _check):
            out = []
            for value in values:
                position = text.find(value)
                out.append(ent("FULLNAME", position, position + len(value)))
            return out

        results, delta = pd.anonymize_batch([("text", text)], seed({}), TAGS,
                                            detect=detect)
        self.assertEqual(len(delta), 300)
        self.assertEqual(len(results[0][1]["anonymized_text"].split(" | ")), 300)
        self.assertEqual(results[0][1]["placeholder_count"], 300)
        self.assertEqual(delta["[FULLNAME_1]"], "v000")
        self.assertEqual(delta["[FULLNAME_300]"], "v299")

    def test_valore_allocato_oltre_4096_caratteri(self):
        long_value = "L" * 5000

        def detect(_text, _check):
            return [ent("FULLNAME", 0, 5000)]

        results, delta = pd.anonymize_batch([("text", long_value)], seed({}), TAGS,
                                            detect=detect)
        self.assertEqual(results[0][1]["anonymized_text"], "[FULLNAME_1]")
        self.assertEqual(delta, {"[FULLNAME_1]": long_value})

    def test_aggregato_oltre_il_limite(self):
        with self.assertRaises(pd.PayloadTooLarge):
            pd.anonymize_batch([("file_1", "a" * 60000), ("file_2", "b" * 60000)],
                               seed({}), TAGS)
        results, _delta = pd.anonymize_batch([("text", "a" * 100000)], seed({}), TAGS)
        self.assertEqual(len(results[0][1]["anonymized_text"]), 100000)

    def test_errore_su_un_input_non_lascia_risultati_parziali(self):
        def detect(_text, _check):
            return [ent("EMAIL", 0, 6)]

        with self.assertRaises(pd.AllocationExhausted):
            pd.anonymize_batch([("file_1", "x@y.it"),
                                ("file_2", "[EMAIL_999999999]")],
                               seed({}), TAGS, detect=detect)

    def test_seed_immutabile_e_riuso_tra_input(self):
        parsed = seed({"[FULLNAME_7]": "Mario Rossi"})
        results, delta = pd.anonymize_batch(
            [("file_1", "Mario Rossi"), ("file_2", "MARIO   ROSSI")],
            parsed, TAGS)
        self.assertEqual(results[0][1]["anonymized_text"], "[FULLNAME_7]")
        self.assertEqual(results[1][1]["anonymized_text"], "[FULLNAME_7]")
        self.assertEqual(delta, {})
        self.assertEqual(parsed.pairs,
                         (("[FULLNAME_7]", "FULLNAME", 7, "Mario Rossi"),))

    def test_stateless_tra_due_chiamate_batch(self):
        inputs = [("file_1", "Mario Rossi"), ("text", "Mario Rossi")]
        detect = detect_literals(("Mario Rossi", "FULLNAME"))
        first = pd.anonymize_batch(inputs, seed({}), TAGS, detect=detect)
        second = pd.anonymize_batch(inputs, seed({}), TAGS, detect=detect)
        self.assertEqual(first, second)

    def test_conteggio_placeholder_per_input(self):
        results, _delta = pd.anonymize_batch(
            [("file_1", "[EMAIL_1] e [EMAIL_1]"), ("text", "niente")],
            seed({}), TAGS)
        self.assertEqual(results[0][1]["placeholder_count"], 2)
        self.assertEqual(results[1][1]["placeholder_count"], 0)

    def test_deadline_batch(self):
        def boom():
            raise pd.DeadlineExceeded()

        with self.assertRaises(pd.DeadlineExceeded):
            pd.anonymize_batch([("text", "Mario")], seed({}), TAGS,
                               check_deadline=boom)

    def test_input_non_stringa(self):
        with self.assertRaises(TypeError):
            pd.anonymize_batch([("text", 123)], seed({}), TAGS)


class StatoEDeadline(unittest.TestCase):
    def test_seed_da_10000_voci_sintetiche_bounded_memory(self):
        limits = guardrail_limits.RequestLimits(10000, 4096, 1048576, 8388608)
        dictionary = {
            "[FULLNAME_%d]" % index: "synthetic-value-%05d" % index
            for index in range(1, limits.seed_entries + 1)
        }
        text = "x" * 100000
        tracemalloc.start()
        try:
            parsed = pd.parse_seed(dictionary, TAGS, limits=limits)
            out = pd.anonymize(text, parsed, TAGS, limits=limits)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(parsed.pairs), limits.seed_entries)
        self.assertEqual(out["anonymized_text"], text)
        self.assertEqual(out["dictionary_delta"], {})
        self.assertLess(peak, 64 * 1024 * 1024)

    def test_memoria_candidati_limitata_a_un_per_partenza(self):
        parsed = seed({"[FULLNAME_%d]" % index: "!" * index
                       for index in range(1, 257)})
        tracemalloc.start()
        try:
            out = pd.anonymize("!" * 2500, parsed, TAGS)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertTrue(out["anonymized_text"].startswith("[FULLNAME_256]"))
        self.assertLess(peak, 12 * 1024 * 1024, "candidate storage scaled with matches")

    def test_stateless_tra_due_chiamate(self):
        parsed = seed({"[FULLNAME_1]": "Mario Rossi"})
        prima = pd.anonymize("Mario Rossi e Rossi", parsed, TAGS)
        seconda = pd.anonymize("Mario Rossi e Rossi", parsed, TAGS)
        self.assertEqual(prima, seconda)
        self.assertEqual(parsed.pairs[0][3], "Mario Rossi")

    def test_deadline_solleva(self):
        def boom():
            raise pd.DeadlineExceeded()

        with self.assertRaises(pd.DeadlineExceeded):
            pd.anonymize("Mario Rossi", pd.parse_seed({}, TAGS), TAGS, check_deadline=boom)

    def test_deadline_controllata_ai_confini(self):
        chiamate = []

        def check():
            chiamate.append(1)

        pd.anonymize("Mario Rossi e Mario", seed({"[FULLNAME_1]": "Mario"}), TAGS,
                     detect=detect_literals(("Rossi", "FULLNAME")), check_deadline=check)
        self.assertGreaterEqual(len(chiamate), 4)


if __name__ == "__main__":
    unittest.main()