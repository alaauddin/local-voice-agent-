"use strict";

import { wakeWord } from "./config.js";

function normalizeArabic(value) {
  return value
    .toLowerCase()
    .replace(/[\u064B-\u065F\u0670]/g, "")
    .replace(/ـ/g, "")
    .replace(/[إأآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/[^؀-ۿa-z0-9\s]/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export const normalizedWakeWord = normalizeArabic(wakeWord);
export const endConversationPhrases = [
  "انهاء المحادثه", "انهي المحادثه", "مع السلامه", "خلاص شكرا", "شكرا غروب",
];

export { normalizeArabic };
