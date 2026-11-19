"""Text cleaning, language codes, phase names, ability slots and server regions (plan Task 1)."""
import unittest

import clean


class CleanText(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(clean.clean_text("<b>Fast</b> Haze", 40), "Fast Haze")
        self.assertEqual(clean.clean_text("#Citadel_X", 40), "Citadel_X")
        self.assertEqual(clean.clean_text("##twice", 40), "twice")
        self.assertEqual(clean.clean_text("a {s:hero} b", 40), "a b")
        self.assertEqual(clean.clean_text("x\u0007y\n z", 40), "xy z")
        self.assertEqual(clean.clean_text("  ", 40), "")
        self.assertEqual(clean.clean_text(None, 40), "")
        long = clean.clean_text("a" * 50, 40)
        self.assertEqual(len(long), 40)
        self.assertEqual(long, "a" * 39 + "…")

    def test_clean_text_has_no_bypass(self):
        # final review: one pass left nested markup, nested curly text and a second '#'; format characters hid a tag
        self.assertEqual(clean.clean_text("<<b>b>bold", 40), "bold")
        self.assertEqual(clean.clean_text("{{x}s:foo} name", 40), "name")
        self.assertEqual(clean.clean_text("# #tok", 40), "tok")
        self.assertEqual(clean.clean_text("<​b>bold</​b>", 40), "bold")
        self.assertEqual(clean.clean_text("ok‮evil", 40), "okevil")
        self.assertEqual(clean.clean_text("##", 40), "")

    def test_clean_text_keeps_words_and_unicode(self):
        self.assertEqual(clean.clean_text("Сборка на Хейз", 40), "Сборка на Хейз")
        self.assertEqual(clean.clean_text("x < y and y > z", 40), "x < y and y > z")


class LangCode(unittest.TestCase):
    def test_lang_code(self):
        self.assertEqual(clean.lang_code(0), "")
        self.assertEqual(clean.lang_code(1), "de")
        self.assertEqual(clean.lang_code(8), "ru")
        self.assertEqual(clean.lang_code(21), "tr")
        self.assertEqual(clean.lang_code(22), "pt")
        self.assertEqual(clean.lang_code(26), "es")
        self.assertEqual(clean.lang_code(99), "")
        self.assertEqual(clean.lang_code(None), "")


class PhaseOf(unittest.TestCase):
    def test_phase_of(self):
        self.assertEqual(clean.phase_of("#Citadel_HeroBuilds_EarlyGame"), "early")
        self.assertEqual(clean.phase_of("#Citadel_HeroBuilds_MidGame"), "mid")
        self.assertEqual(clean.phase_of("#Citadel_HeroBuilds_LateGame"), "late")
        self.assertEqual(clean.phase_of("Early game"), "early")
        self.assertEqual(clean.phase_of("LANING"), "early")
        self.assertEqual(clean.phase_of("mid"), "mid")
        self.assertEqual(clean.phase_of("Late/Lux"), "late")
        self.assertEqual(clean.phase_of("situationals"), "situational")
        self.assertEqual(clean.phase_of("Flex"), "situational")
        self.assertEqual(clean.phase_of("green spike 4800 800s maybe"), "green spike 4800 800s m…")
        self.assertEqual(clean.phase_of("CORE"), "CORE")
        self.assertEqual(clean.phase_of(""), "Items")
        self.assertEqual(clean.phase_of(None), "Items")
        self.assertEqual(clean.phase_of("{s:x}"), "Items")


# made-up ability item ids for the four signature abilities of a hero
A1, A2, A3, A4 = 101, 202, 303, 404
SLOT_OF = {A1: 1, A2: 2, A3: 3, A4: 4}
ID_OF = {1: A1, 2: A2, 3: A3, 4: A4}


def order(slots, unlocks=True):
    """A currency_changes list: 4 unlocks (type 2), then one type-1 spend per slot, deltas -1/-2/-5 by the ability's nth point."""
    out = []
    if unlocks:
        out += [{"ability_id": ID_OF[s], "currency_type": 2, "delta": -1} for s in (1, 2, 3, 4)]
    seen = {}
    for s in slots:
        seen[s] = seen.get(s, 0) + 1
        out.append({"ability_id": ID_OF[s], "currency_type": 1, "delta": (-1, -2, -5)[min(seen[s], 3) - 1]})
    return out


class AbilitySlots(unittest.TestCase):
    SHAPE = [3, 2, 2, 2, 4, 4, 4, 3, 3, 1, 1, 1]

    def test_ability_slots(self):
        self.assertEqual(clean.ability_slots(order(self.SHAPE), SLOT_OF), self.SHAPE)

    def test_long_orders_cut_at_12(self):
        ch = order(self.SHAPE) + order([1, 2, 3, 4] * 5, unlocks=False)
        self.assertEqual(len(ch), 36)
        self.assertEqual(clean.ability_slots(ch, SLOT_OF), self.SHAPE)

    def test_unknown_and_refunds_skipped(self):
        ch = order([1, 2])
        ch.insert(5, {"ability_id": 999, "currency_type": 1, "delta": -1})
        ch.insert(6, {"ability_id": A3, "currency_type": 1, "delta": 1})
        self.assertEqual(clean.ability_slots(ch, SLOT_OF), [1, 2])
        self.assertEqual(clean.ability_slots([], SLOT_OF), [])
        self.assertEqual(clean.ability_slots(None, SLOT_OF), [])


class RegionOf(unittest.TestCase):
    def test_region_of(self):
        for r in ("eu_north", "eu_west", "eu_east", "dpkt-frankfurt", "london", "helsinki", "poland", "spain", "falkenstein"):
            self.assertEqual(clean.region_of(r), "eu", r)
        for r in ("us_southeast", "us_north_central", "us_east", "us_south_central", "us_southwest", "us_west"):
            self.assertEqual(clean.region_of(r), "na", r)
        for r in ("asia", "hong_kong", "japan", "singapore", "korea"):
            self.assertEqual(clean.region_of(r), "asia", r)
        for r in ("south_america", "argentina", "chile", "peru"):
            self.assertEqual(clean.region_of(r), "sa", r)
        self.assertEqual(clean.region_of("australia"), "oce")
        self.assertIsNone(clean.region_of(None))
        self.assertIsNone(clean.region_of("moon_base"))


if __name__ == "__main__":
    unittest.main()
