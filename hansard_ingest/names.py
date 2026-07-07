"""Name cleaning, Chair role inference, and fuzzy matching.

The Hansard payload mixes raw labels ("Mr Speaker", "The Minister for
Foreign Affairs (Dr Vivian Balakrishnan)", "Mr Chan Chun Sing (Tanjong
Pagar), Coordinating Minister...") with attendance entries. This module
normalises those into clean person names and matches speaker labels back
to the attendance list using ``difflib`` (kept deterministic — no LLM,
no network).
"""

import re
from typing import List, Optional, Tuple

HONORIFICS_RE = r"(?:Mr|Ms|Mrs|Mdm|Madam|Miss|Dr|Prof|Professor|Er\s+Dr|Assoc\s*Prof\.?\s*Dr\.?|Assoc\s*Prof\.?)"

# Names that the Chair calls out (not substantive speeches)
CHAIR_CALL_HONORIFICS_RE = r"(?:Mr|Ms|Mrs|Mdm|Madam|Miss|Dr|Assoc\s+Prof\s+Dr|Assoc\s+Prof|Professor|Prof|Er)"


def chair_role(chair_raw: str):
    if not chair_raw:
        return None
    u = chair_raw.upper()
    if "DEPUTY SPEAKER" in u:
        return "deputy_speaker"
    if "SPEAKER" in u:
        return "speaker"
    return None


def strip_trailing_chair_call(text: str) -> str:
    if not text:
        return text
    return re.sub(r"\s+(Mr|Madam)\s+Speaker\.?\s*$", "", text, flags=re.I).rstrip()


def name_key(name_raw: str) -> str:
    """Stable key for matching person names across decorated labels."""
    if not name_raw:
        return ""
    s = str(name_raw).strip()
    s = re.sub(r"^(%s)\s+" % HONORIFICS_RE, "", s, flags=re.I)
    s = re.sub(r"\([^)]*\)", "", s)      # remove constituency etc
    s = s.split(",")[0]                  # remove roles/portfolios
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s.upper()


def extract_chair_marker(text: str):
    t = (text or "").strip()
    if "in the Chair" not in t or not t.startswith("[") or "SPEAKER" not in t.upper():
        return None
    m = re.match(r"^\[(.+?)\s+in\s+the\s+Chair\.?\]\s*$", t, flags=re.I)
    return m.group(1).strip() if m else None


def infer_chair_from_speaker_label(speaker_raw: str) -> Optional[str]:
    """If the speaker label itself indicates the Chair, return an appropriate chair_name_raw."""
    if not speaker_raw:
        return None
    s = str(speaker_raw).strip()
    u = s.upper()
    # Common Hansard labels
    if "DEPUTY SPEAKER" in u:
        return s  # e.g. 'Mr Deputy Speaker' or 'Mr Deputy Speaker (Mr X...)'
    if u in {"MR SPEAKER", "MADAM SPEAKER", "SPEAKER"} or "SPEAKER" in u:
        # Avoid catching 'Deputy Speaker' which is handled above
        if "DEPUTY" not in u:
            return s
    return None


def is_question_paper_item(speaker_raw: str, speech: str) -> bool:
    """
    Detect non-spoken Question Time listings like:
      '1 Mr X asked the Minister ...'
    These are not debate speeches.
    """
    if not speaker_raw or not speech:
        return False
    s = re.sub(r"\s+", " ", speech.replace("\xa0", " ")).strip()
    sp = re.sub(r"\s+", " ", speaker_raw).strip()

    # Must start with a question number, then the same speaker name, then "asked"
    pat = re.compile(rf"^\d+\s+{re.escape(sp)}\s+asked\b", flags=re.I)
    if not pat.search(s):
        return False

    # Usually directed at Minister/PM/etc
    return re.search(
        r"\basked\s+(?:the\s+)?(?:minister|prime minister|deputy prime minister|parliamentary secretary)\b",
        s, flags=re.I
    ) is not None


# Detect procedural Chair call-outs like 'Mr Patrick Tay.' or 'Er Dr Lee Bee Wah.'

def is_chair_call_to_member(text: str) -> bool:
    """Detect Chair call-outs like 'Mr Patrick Tay.' or 'Er Dr Lee Bee Wah.'

    These are procedural (Chair calling the next Member), not substantive speeches.
    """
    if not text:
        return False
    t = re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()
    # Common formats end with a period; keep this conservative
    if not t.endswith("."):
        return False
    # Very short and looks like a name with honorific
    words = re.findall(r"\b\w+\b", t)
    if len(words) > 7:
        return False
    if not re.match(rf"^({CHAIR_CALL_HONORIFICS_RE})\b", t, flags=re.I):
        return False
    # Avoid treating actual sentences as call-outs
    if re.search(r"\b(thank|ask|welcome|move|agree|urge|request|clarif|supplementary|question)\b", t, flags=re.I):
        return False
    return True


def extract_person_from_speaker_attendance(mp_name_raw: str) -> Optional[str]:
    """Extract person name from strings like: 'Mr SPEAKER (Mr Seah Kian Peng (Marine Parade)).'"""
    if not mp_name_raw:
        return None
    s = str(mp_name_raw).strip()

    # Take the substring inside the OUTERMOST parentheses (handles nested parentheses)
    l = s.find("(")
    r = s.rfind(")")
    if l == -1 or r == -1 or r <= l:
        return None

    inner = s[l + 1 : r].strip().strip(".")

    # Drop trailing constituency parentheses if present
    inner = re.sub(r"\s*\([^)]*\)\s*$", "", inner).strip(" .")

    # Drop honorific for chair_name output
    inner = re.sub(r"^(%s)\s+" % HONORIFICS_RE, "", inner, flags=re.I)

    return inner.strip() or None



def extract_person_from_name(raw: str) -> Optional[str]:
    """Best-effort extraction of a person's name from a label; keeps it deterministic (no web/LLM)."""
    if not raw:
        return None
    s = str(raw).strip()
    # Match a person name inside parentheses, including multi-token honorifics like 'Assoc Prof Dr'
    m = re.search(r"\((%s)\s+[^)]+\)" % HONORIFICS_RE, s, flags=re.I)
    if m:
        inner = m.group(0).strip("() ")
        # Remove any trailing constituency parentheses within the captured text
        inner = re.sub(r"\s*\([^)]*\)\s*$", "", inner).strip(" .")
        # Remove leading honorific(s)
        inner = re.sub(r"^(?:(%s)\s+)+" % HONORIFICS_RE, "", inner, flags=re.I).strip()
        inner = re.sub(r"\s+", " ", inner).strip(" .")
        return inner.strip() or None

    # If label is 'Mr Speaker' or 'Mr Deputy Speaker' etc, return None (resolved via attendance map)
    if re.search(r"\bSPEAKER\b", s, flags=re.I):
        return None

    # Otherwise treat it as already a person name; remove honorific, any parentheses, and trailing roles
    s2 = re.sub(r"^(%s)\s+" % HONORIFICS_RE, "", s, flags=re.I)
    s2 = s2.split(",", 1)[0].strip()
    s2 = re.sub(r"\([^)]*\)", " ", s2)  # remove any parentheses anywhere
    s2 = re.sub(r"\s+", " ", s2).strip(" .")
    return s2.strip() or None


# ----------- Fallback extractor for parenthesized person names -----------

def extract_last_parenthesized_text(s: str) -> Optional[str]:
    """Return the last parenthesized chunk as a name-like string.

    Useful when speaker_raw is a role title like:
      'The Minister for ... (Assoc Prof Dr Yaacob Ibrahim)'
    where the parentheses may not be captured by stricter patterns.
    """
    if not s:
        return None
    parts = re.findall(r"\(([^()]*)\)", str(s))
    if not parts:
        return None
    last = parts[-1].strip().strip(".")
    # Must look name-like (at least 2 alphabetic tokens)
    if len(re.findall(r"[A-Za-z]+", last)) < 2:
        return None
    # Strip leading honorific tokens if present
    last = re.sub(r"^(?:(%s)\s+)+" % HONORIFICS_RE, "", last, flags=re.I).strip()
    last = re.sub(r"\s+", " ", last).strip(" .")
    return last or None


# ----------- Name cleaning and fuzzy matching helpers -----------

def clean_mp_name_from_attendance(raw: str) -> Optional[str]:
    """Return the person's name (no honorific, no constituency, no portfolios).

    Examples:
      - 'Mr Chan Chun Sing (Tanjong Pagar), Coordinating Minister ...' -> 'Chan Chun Sing'
      - 'Miss Rachel Ong (West Coast).' -> 'Rachel Ong'
      - 'Mr SPEAKER (Mr Seah Kian Peng (Marine Parade)).' -> 'Seah Kian Peng'
    """
    if not raw:
        return None
    s = str(raw).strip().rstrip(".")

    # Special case: presiding-officer attendance lines nest the person's real
    # name in parentheses, e.g.
    #   'Mr SPEAKER (Mr Seah Kian Peng (Marine Parade)).'
    #   'Mr Deputy Speaker (Mr Christopher de Souza (Holland-Bukit Timah)).'
    # extract_person_from_speaker_attendance() reads the OUTERMOST parentheses,
    # so it correctly strips the doubly-nested constituency. For the Deputy
    # Speaker variant we only take this path when a person (honorific-prefixed)
    # is actually nested, to avoid misreading a bare '(Constituency)' as a name.
    u = s.upper()
    is_speaker_paren = "DEPUTY SPEAKER" not in u and re.search(r"\bSPEAKER\s*\(", s, flags=re.I)
    is_deputy_person = "DEPUTY SPEAKER" in u and re.search(
        r"\bSPEAKER\s*\(\s*%s\b" % HONORIFICS_RE, s, flags=re.I
    )
    if is_speaker_paren or is_deputy_person:
        sp = extract_person_from_speaker_attendance(s)
        if sp:
            return sp

    # If the label contains a person's name in parentheses (e.g. role titles in speech list), extract it
    # Examples: 'The Minister for Foreign Affairs (Dr Vivian Balakrishnan)'
    if re.search(r"\((%s)\s+[^)]+\)" % HONORIFICS_RE, s, flags=re.I):
        person = extract_person_from_name(s)
        if person:
            return person

    # Remove everything after the first comma (portfolios, roles)
    s = s.split(",", 1)[0].strip()

    # Remove trailing constituency parentheses
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip(" .")

    # Remove one or more leading honorific tokens (e.g. 'Assoc Prof Dr', 'Dr', etc.)
    s = re.sub(r"^(?:(%s)\s+)+" % HONORIFICS_RE, "", s, flags=re.I).strip()

    # Remove any lingering all-caps SPEAKER tokens (rare)
    s = re.sub(r"\bSPEAKER\b", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s).strip()

    return s or None


def norm_for_match(s: str) -> str:
    if not s:
        return ""
    x = str(s)
    x = x.replace("\u00a0", " ")
    x = re.sub(r"\([^)]*\)", " ", x)  # drop parentheses chunks
    x = x.split(",", 1)[0]
    x = re.sub(r"^(%s)\s+" % HONORIFICS_RE, "", x, flags=re.I)
    x = re.sub(r"\b(MINISTER|PRIME|DEPUTY|PARLIAMENTARY|SECRETARY|SPEAKER)\b", " ", x, flags=re.I)
    x = re.sub(r"[^A-Za-z\s]", " ", x)
    x = re.sub(r"\s+", " ", x).strip().upper()
    return x


def best_fuzzy_match(query: str, choices: List[str]) -> Tuple[Optional[str], float]:
    """Return (best_choice, score) using difflib; score in [0,1]."""
    from difflib import SequenceMatcher

    q = norm_for_match(query)
    if not q:
        return None, 0.0

    best = None
    best_score = 0.0
    for c in choices:
        cs = norm_for_match(c)
        if not cs:
            continue
        sc = SequenceMatcher(None, q, cs).ratio()
        if sc > best_score:
            best_score = sc
            best = c
    return best, best_score
