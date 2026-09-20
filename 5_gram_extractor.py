import re
import math
from pathlib import Path
from collections import Counter, defaultdict

# Set the target folder path here.
# You can change this to the directory containing your files.
FOLDER_PATH = '/Users/danblumenau/Downloads/french_transcripts'

# Set the minimum and maximum length of the n-grams
# Set MAX_NGRAM_LENGTH = None to dynamically find the longest repeating phrases.
MIN_NGRAM_LENGTH = 3
MAX_NGRAM_LENGTH = 4

# Optional: Set of words the n-gram MUST start with (e.g., {'je', 'tu', 'il', 'elle', 'on'}).
# Leave as an empty set to allow any starting word.
START_WORDS = frozenset()

# Words to completely remove from the token stream.
# Removing these allows phrases like "je ne sais pas" and "je sais" to merge.
REMOVE_WORDS = frozenset({'pas','ne'})

# Words that cannot end an n-gram, but remain visible within phrases.
# Prevents function words from being useless trailing words in results.
BLACKLIST = frozenset({
    'euh', 'mh',
    'un', 'une', 'des', 'le', 'la', 'les', 'en', 'à', 'du', 'au',
    'je', 'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles',
    "j'ai", "j'étais", "c'est", "c'était",
    'que', 'qui', 'de', 'et', 'mais', 'ou', 'donc', 'ce'
})

# Dictionary to merge/replace specific words or multi-word phrases.
# Format: {'original phrase': 'target phrase'}
REPLACEMENTS = {}

# Number of top results to display
TOP_N = 20

# Number of context examples to display per n-gram
TOP_EXTENSIONS = 5

# Scoring mode:
#   'frequency' - raw count
#   'leverage'  - frequency x MI (association strength)
#   'frames'    - two-tier analysis: sentence starters + portable content blocks
SCORING_MODE = 'frames'

# Frame and chunk length ranges (for 'frames' mode)
MIN_STARTER = 3
MAX_STARTER = 4
MIN_BLOCK = 2
MAX_BLOCK = 3

# Diversity: skip n-grams sharing this many leading words with an already-selected item.
# Set to None to disable diversity filtering.
MIN_SHARED_PREFIX = 3

# Number of building blocks (portable chunks) to display
TOP_CHUNKS = 15

# Internal constants
_SIL = '<SIL>'
_NOISE_MARKERS = frozenset({'_', '%', '#'})

# Common interrogative structures (used by is_question)
_QUESTION_MARKERS = (
    "est-ce que", "est ce que",
    "qu'est-ce", "qu'est ce",
    "n'est-ce pas", "n'est ce pas",
    "est-il", "est il",
    "a-t-il", "a t il",
    "pourquoi", "comment", "combien", "quel", "quelle", "quels", "quelles"
)


def merge_apostrophe_tokens(tokens: list[str]) -> list[str]:
    """
    Merges tokens ending with an apostrophe (e.g., "c'", "qu'")
    with the following word to form a single token (e.g., "c'est").
    """
    merged = []
    i = 0
    while i < len(tokens):
        if tokens[i].endswith("'") and i + 1 < len(tokens) and tokens[i+1] != _SIL:
            merged.append(tokens[i] + tokens[i+1])
            i += 2
        else:
            merged.append(tokens[i])
            i += 1
    return merged


def parse_textgrid_for_tokens(filepath: Path) -> dict[str, list[str]]:
    """
    Parses a Praat TextGrid file and extracts an ordered list of tokens
    for each valid speaker tier.
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return {}

    tiers = defaultdict(list)
    current_tier_name = None

    # Step 1: Read the file and group all text intervals by their Tier Name
    for line in lines:
        line = line.strip()

        if line.startswith('name ='):
            # Extract the tier name (e.g., "enqueteur" or "enqueteur[tok_min]")
            match = re.search(r'"(.*?)"', line)
            if match:
                current_tier_name = match.group(1)

        elif line.startswith('text =') and current_tier_name is not None:
            # Extract the spoken text or transcription noise
            match = re.search(r'"(.*?)"', line)
            if match:
                text = match.group(1)
                tiers[current_tier_name].append(text)

    # Step 2: Extract ordered tokens from the most reliable tiers available
    # We prefer [tok_min] because the words are already perfectly tokenized
    tok_tiers = [name for name in tiers if name.endswith('[tok_min]')]

    tier_tokens_dict = {}

    if tok_tiers:
        # Use the pre-tokenized tiers
        for tier_name in tok_tiers:
            tokens = []
            for token in tiers[tier_name]:
                tok = token.strip().lower()
                # Treat noise/silence markers as structural breaks
                if tok in _NOISE_MARKERS:
                    tokens.append(_SIL)
                elif tok:
                    tokens.append(tok)
            tier_tokens_dict[tier_name] = merge_apostrophe_tokens(tokens)

    else:
        # Fallback: Process the base tiers (names without brackets)
        base_tiers = [name for name in tiers if '[' not in name]
        for tier_name in base_tiers:
            tokens = []
            for interval_text in tiers[tier_name]:
                cleaned_text = interval_text.strip().lower()

                # Replace noise markers with explicit silence boundaries
                for noise in _NOISE_MARKERS:
                    cleaned_text = cleaned_text.replace(noise, f' {_SIL} ')

                # Regex logic:
                # <SIL> matches our boundary marker.
                # [^\W\d_]+'? matches any Unicode letters (ignoring numbers/symbols)
                # and optionally grabs a trailing apostrophe (e.g., "d'", "l'").
                words = re.findall(r"<SIL>|[^\W\d_]+'?", cleaned_text)

                tokens.extend(words)
            tier_tokens_dict[tier_name] = merge_apostrophe_tokens(tokens)

    return tier_tokens_dict


def has_stutter(ngram: tuple[str, ...]) -> bool:
    """
    Checks if an n-gram contains obvious stuttering or repetitions.
    Filters out consecutive identical unigrams (e.g., 'je je')
    and consecutive identical bigrams (e.g., "c' est c' est").
    """
    # Check for unigram repetitions (A A)
    if any(ngram[i] == ngram[i+1] for i in range(len(ngram) - 1)):
        return True

    # Check for bigram repetitions (A B A B)
    if any(ngram[i:i+2] == ngram[i+2:i+4] for i in range(len(ngram) - 3)):
        return True

    # Check for trigram repetitions (A B C A B C)
    if any(ngram[i:i+3] == ngram[i+3:i+6] for i in range(len(ngram) - 5)):
        return True

    return False


def is_question(ngram: tuple[str, ...]) -> bool:
    """
    Checks if an n-gram is likely to be a question.
    """
    phrase = " ".join(ngram)

    # Check if phrase starts with a question word or contains a strong question marker
    if any(marker in phrase for marker in _QUESTION_MARKERS):
        # Allow phrases that use "est-ce que" to mean "that's what"
        # (e.g., "c'est ce que", "c' est ce que")
        if "c'est ce que" in phrase or "c' est ce que" in phrase:
             return False
        return True

    return False


def is_subsequence(sub: tuple, main: tuple) -> bool:
    """
    Checks if tuple `sub` is a contiguous subsequence of tuple `main`.
    """
    sub_len = len(sub)
    for i in range(len(main) - sub_len + 1):
        if main[i:i+sub_len] == sub:
            return True
    return False


def filter_redundant_ngrams(ngram_counts: Counter, top_n: int = TOP_N) -> Counter:
    """
    Removes shorter n-grams if they only ever appear as a fragment
    of a longer n-gram with the exact same frequency.
    """
    # Pre-filter: only check n-grams that could realistically appear in the results.
    # Use a large buffer (top_n * 20) because the redundancy filter will remove many
    # of these, and we need enough survivors to fill the final top_n.
    buffer = top_n * 20
    if len(ngram_counts) > buffer:
        threshold = ngram_counts.most_common(buffer)[-1][1]
        ngram_counts = Counter({ng: c for ng, c in ngram_counts.items() if c >= threshold})

    # Sort n-grams by length descending, so we process the longest phrases first
    sorted_ngrams = sorted(ngram_counts.keys(), key=len, reverse=True)
    filtered_counts = Counter()

    # Dictionary to group kept n-grams by their count for fast lookups
    ngrams_by_count: dict[int, list[tuple]] = defaultdict(list)

    for ngram in sorted_ngrams:
        count = ngram_counts[ngram]
        is_redundant = False

        # Only check for redundancy against longer n-grams that share the EXACT same count
        if count in ngrams_by_count:
            for longer_ngram in ngrams_by_count[count]:
                if is_subsequence(ngram, longer_ngram):
                    is_redundant = True
                    break

        # If it wasn't swallowed by a longer phrase, we keep it!
        if not is_redundant:
            filtered_counts[ngram] = count
            ngrams_by_count[count].append(ngram)

    return filtered_counts


def _split_on_silence(tokens: list[str]) -> list[list[str]]:
    """Split token list into segments separated by <SIL> markers."""
    segments = []
    current: list[str] = []
    for tok in tokens:
        if tok == _SIL:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def extract_ngrams(tokens: list[str], min_n: int, max_n: int | None,
                    start_words: frozenset[str]) -> Counter:
    """
    Takes an ordered list of tokens and yields consecutive n-grams
    within the specified length range. Prevents n-grams from crossing
    over <SIL> boundary markers, filters out conversational stutters,
    excludes questions, and optionally filters by specific starting words.
    """
    ngrams = Counter()
    segments = _split_on_silence(tokens)

    for segment in segments:
        # If max_n is None, allow n-grams up to the total length of the current segment
        actual_max = max_n if max_n is not None else len(segment)

        for n in range(min_n, actual_max + 1):
            # We need at least n words to make an n-gram
            if len(segment) < n:
                continue

            for i in range(len(segment) - n + 1):
                ngram = tuple(segment[i:i+n])

                # Enforce starting word condition if a set is provided
                if start_words and ngram[0] not in start_words:
                    continue

                # Tally the n-gram if it doesn't contain a stutter pattern
                # and is NOT a question
                if not has_stutter(ngram) and not is_question(ngram):
                    ngrams[ngram] += 1

    return ngrams


def apply_replacements(tokens: list[str], replacements: dict[str, str]) -> list[str]:
    """
    Scans the token list and replaces sequences of words based on the REPLACEMENTS dictionary.
    Matches longest phrases first to prevent partial replacements.
    """
    if not replacements:
        return tokens

    # Sort replacements by phrase length (longest first) to avoid partial matches
    sorted_reps = sorted(replacements.items(), key=lambda x: len(x[0].split()), reverse=True)
    # Convert strings into lists/tuples of tokens
    rep_rules = [(tuple(k.split()), v.split()) for k, v in sorted_reps]

    result = []
    i = 0
    while i < len(tokens):
        match_found = False
        for target_tuple, replacement_tokens in rep_rules:
            length = len(target_tuple)
            # Check if the upcoming tokens match our target phrase
            if tuple(tokens[i:i+length]) == target_tuple:
                result.extend(replacement_tokens)
                i += length
                match_found = True
                break

        if not match_found:
            result.append(tokens[i])
            i += 1
    return result


def find_example_usages(ngram: tuple[str, ...], intervals: list[list[str]],
                        blacklist: frozenset[str], num_examples: int,
                        max_len: int = 12) -> list[tuple[str, int]]:
    """Find diverse, complete example continuations of a frame from raw speech.
    Extracts everything after the frame until the next silence boundary,
    giving real example sentences that show the frame in action."""
    n_len = len(ngram)
    continuations: list[tuple[str, ...]] = []

    for tokens in intervals:
        for i in range(len(tokens) - n_len):
            if tuple(tokens[i:i+n_len]) == ngram:
                rest = []
                for j in range(i + n_len, min(i + n_len + max_len, len(tokens))):
                    if tokens[j] == _SIL:
                        break
                    rest.append(tokens[j])
                # Keep if at least 2 words and doesn't trail off on a function word
                if len(rest) >= 2 and rest[-1] not in blacklist:
                    continuations.append(tuple(rest))

    # Rank by frequency, then prefer longer examples
    counted = Counter(continuations)
    ranked = sorted(counted.items(), key=lambda x: (x[1], len(x[0])), reverse=True)

    return [(" ".join(cont), count) for cont, count in ranked[:num_examples]]


def compute_mi_scores(ngram_counts: Counter, word_freqs: Counter,
                      total_tokens: int) -> dict[tuple, float]:
    """Compute normalised Pointwise Mutual Information for each n-gram.
    MI measures how much more often words co-occur than chance predicts.
    High MI = a genuine formulaic chunk worth learning as a unit.
    Normalised by n-gram length to avoid bias towards longer phrases."""
    scores = {}
    for ngram, count in ngram_counts.items():
        n = len(ngram)
        p_ngram = count / max(total_tokens - n + 1, 1)
        p_independent = 1.0
        for word in ngram:
            p_independent *= word_freqs.get(word, 1) / total_tokens
        if p_independent > 0 and p_ngram > 0:
            scores[ngram] = math.log2(p_ngram / p_independent) / n
        else:
            scores[ngram] = 0.0
    return scores


def compute_slot_diversity(all_ngram_counts: Counter) -> dict[tuple, int]:
    """For each n-gram, count how many unique words follow it in the corpus.
    High diversity = productive frame with an open slot.
    Low diversity = fixed phrase with predictable continuation."""
    followers = defaultdict(set)
    for ngram in all_ngram_counts:
        if len(ngram) >= 2:
            prefix = ngram[:-1]
            followers[prefix].add(ngram[-1])
    return {prefix: len(words) for prefix, words in followers.items()}


def compute_filler_portability(all_ngram_counts: Counter,
                               blacklist: frozenset[str],
                               remove_words: frozenset[str]) -> dict[str, set[tuple]]:
    """For each word, find how many distinct frames it can slot into.
    High portability = a word worth learning early because it works everywhere."""
    filler_frames = defaultdict(set)
    for ngram in all_ngram_counts:
        if len(ngram) >= 2:
            frame = ngram[:-1]
            filler = ngram[-1]
            if filler not in blacklist and filler not in remove_words and filler != _SIL:
                filler_frames[filler].add(frame)
    return dict(filler_frames)


def select_diverse_results(candidates: list[tuple[tuple, int, float, float]],
                           top_n: int, min_prefix: int | None) -> list:
    """Greedy selection: pick highest-scoring n-grams, skipping variants
    that share a long prefix with an already-selected chunk.
    Each candidate is (ngram, count, mi, score)."""
    selected = []
    for ngram, count, mi, score in candidates:
        if len(selected) >= top_n:
            break
        if min_prefix is not None:
            is_variant = False
            for sel_ngram, _, _, _ in selected:
                shared = 0
                for a, b in zip(ngram, sel_ngram):
                    if a == b:
                        shared += 1
                    else:
                        break
                if shared >= min_prefix:
                    is_variant = True
                    break
            if is_variant:
                continue
        selected.append((ngram, count, mi, score))
    return selected


def analyze_building_blocks(all_intervals, start_words, blacklist):
    """Find sentence starters (frames) and portable content blocks (chunks).

    Frames are 2-4 word beginnings scored by frequency x diversity.
    Chunks are 2-4 word content blocks scored by frequency x portability.
    Together, N frames x M chunks can produce up to NxM sentences."""
    connectors = frozenset({
        'que', 'de', 'à', 'qui',
        'je', 'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles',
    })
    noise = frozenset({'euh', 'mh'})

    frame_counts = Counter()
    frame_to_chunks = defaultdict(Counter)
    chunk_to_frames = defaultdict(Counter)

    for tokens in all_intervals:
        for segment in _split_on_silence(tokens):
            for i in range(len(segment)):
                if start_words and segment[i] not in start_words:
                    continue

                for f_len in range(MIN_STARTER, MAX_STARTER + 1):
                    f_end = i + f_len
                    if f_end > len(segment):
                        break
                    frame = tuple(segment[i:f_end])

                    if any(w in noise for w in frame) or has_stutter(frame):
                        continue
                    if is_question(frame):
                        continue

                    frame_counts[frame] += 1

                    for c_len in range(MIN_BLOCK, MAX_BLOCK + 1):
                        c_end = f_end + c_len
                        if c_end > len(segment):
                            break
                        chunk = tuple(segment[f_end:c_end])

                        if chunk[0] in connectors or chunk[-1] in blacklist:
                            continue
                        if any(w in noise for w in chunk) or has_stutter(chunk):
                            continue
                        if has_stutter(frame + chunk):
                            continue
                        # Skip if chunk trails into a restart of the frame
                        frame_restart = False
                        for k in range(1, min(len(chunk), len(frame)) + 1):
                            if chunk[-k:] == frame[:k]:
                                frame_restart = True
                                break
                        if frame_restart:
                            continue

                        frame_to_chunks[frame][chunk] += 1
                        chunk_to_frames[chunk][frame] += 1

    # Score frames: frequency x chunk diversity
    frame_scored = []
    for frame, count in frame_counts.items():
        diversity = len(frame_to_chunks.get(frame, {}))
        if diversity < 2:
            continue
        frame_scored.append((frame, count, diversity, count * diversity))
    frame_scored.sort(key=lambda x: x[3], reverse=True)

    # Score chunks: total uses x frame portability
    chunk_scored = []
    for chunk, frames in chunk_to_frames.items():
        portability = len(frames)
        if portability < 2:
            continue
        total = sum(frames.values())
        chunk_scored.append((chunk, total, portability, total * portability))
    chunk_scored.sort(key=lambda x: x[3], reverse=True)

    top_frames = select_diverse_results(frame_scored, TOP_N, MIN_SHARED_PREFIX)
    top_chunks = select_diverse_results(chunk_scored, TOP_CHUNKS, MIN_SHARED_PREFIX)

    return top_frames, top_chunks, frame_to_chunks, chunk_to_frames


def main():
    print(f"Scanning directory: '{FOLDER_PATH}'")

    # Locate all TextGrid files in the folder (or standard text files if you saved them as .txt)
    folder = Path(FOLDER_PATH)
    filepaths = list(folder.glob('*.TextGrid')) or list(folder.glob('*.txt'))

    if not filepaths:
        print("No files found! Please ensure 'FOLDER_PATH' points to the correct directory.")
        return

    global_ngrams = Counter()
    word_freqs = Counter()
    total_tokens = 0
    all_intervals = []

    for filepath in filepaths:
        # Extract the tokens mapped by speaker/tier
        tier_tokens_dict = parse_textgrid_for_tokens(filepath)

        # Tally the n-grams for every speaker in the file
        for tier_name, tokens in tier_tokens_dict.items():

            # Step 1: Apply replacements (supports multi-word phrases)
            replaced_tokens = apply_replacements(tokens, REPLACEMENTS)

            # Step 2: Remove words that should be stripped entirely
            filtered_tokens = [tok for tok in replaced_tokens if tok not in REMOVE_WORDS]

            # Store for example sentence extraction later
            all_intervals.append(filtered_tokens)

            # Count individual word frequencies (excluding silence markers)
            real_words = [t for t in filtered_tokens if t != _SIL]
            word_freqs.update(real_words)
            total_tokens += len(real_words)

            tier_ngrams = extract_ngrams(filtered_tokens, MIN_NGRAM_LENGTH, MAX_NGRAM_LENGTH, START_WORDS)
            global_ngrams.update(tier_ngrams)

    print(f"Analysed {len(all_intervals)} speech tiers from {len(filepaths)} files ({total_tokens:,} tokens).")

    if SCORING_MODE == 'frames':
        # Two-tier building-block analysis
        top_frames, top_chunks, f2c, c2f = analyze_building_blocks(
            all_intervals, START_WORDS, BLACKLIST)

        print(f"\n{'='*60}")
        print("  SENTENCE STARTERS")
        print("  High-frequency beginnings that combine with many endings.")
        print(f"{'='*60}\n")

        if not top_frames:
            print("  No frames found. Try broadening START_WORDS or BLACKLIST.\n")
        else:
            for rank, (frame, count, diversity, _) in enumerate(top_frames, 1):
                phrase = " ".join(frame)
                print(f"  {rank}. \"{phrase} ...\"  ({count} uses, {diversity} ways to finish)")
                # Grab extra candidates, then drop chunks that are just
                # a prefix of a longer chunk at the same or higher count.
                candidates = f2c[frame].most_common(TOP_EXTENSIONS * 3)
                shown = 0
                for chunk, combo_count in candidates:
                    if shown >= TOP_EXTENSIONS:
                        break
                    if any(oc[:len(chunk)] == chunk and len(oc) > len(chunk) and occ >= combo_count
                           for oc, occ in candidates):
                        continue
                    combo = f"{phrase} {' '.join(chunk)}"
                    suffix = f"  (x{combo_count})" if combo_count > 1 else ""
                    print(f"       {combo}{suffix}")
                    shown += 1
                print()

        print(f"{'='*60}")
        print("  BUILDING BLOCKS")
        print("  Portable endings that slot into many different starters.")
        print(f"{'='*60}\n")

        if not top_chunks:
            print("  No chunks found. Try broadening BLACKLIST.\n")
        else:
            for rank, (chunk, total, portability, _) in enumerate(top_chunks, 1):
                chunk_phrase = " ".join(chunk)
                print(f"  {rank}. \"{chunk_phrase}\"  (fits {portability} starters, {total} uses)")
                for frame, _ in c2f[chunk].most_common(3):
                    print(f"       {' '.join(frame)} {chunk_phrase}")
                print()

        n_f = len(top_frames)
        n_c = len(top_chunks)
        print(f"{'='*60}")
        print(f"  {n_f} starters x {n_c} blocks = up to {n_f * n_c} sentences")
        print(f"  from just {n_f + n_c} memory items.")
        print(f"{'='*60}")
        return

    # ---- Traditional n-gram pipeline (leverage / frequency modes) ----
    all_ngram_counts = global_ngrams
    global_ngrams = filter_redundant_ngrams(global_ngrams)

    if SCORING_MODE == 'leverage':
        mi_scores = compute_mi_scores(global_ngrams, word_freqs, total_tokens)
        scored = []
        for ngram, count in global_ngrams.items():
            mi = mi_scores.get(ngram, 0)
            score = count * max(mi, 0)
            scored.append((ngram, count, mi, score))
        scored.sort(key=lambda x: x[3], reverse=True)
        top_results = select_diverse_results(scored, TOP_N, MIN_SHARED_PREFIX)
    else:
        top_results = [(ng, c, 0.0, c) for ng, c in global_ngrams.most_common(TOP_N)]

    max_label = MAX_NGRAM_LENGTH or "Unlimited"
    mode_labels = {
        'leverage': 'HIGHEST-LEVERAGE CHUNKS',
        'frequency': 'MOST FREQUENT N-GRAMS',
    }
    print(f"\n--- {mode_labels.get(SCORING_MODE, 'TOP')} (Lengths {MIN_NGRAM_LENGTH}-{max_label}) ---")
    if SCORING_MODE == 'leverage':
        print("Ranked by frequency x association strength, with diversity filtering.")
    print()

    if not top_results:
        print("No valid n-grams were found.")
    else:
        for rank, (ngram, count, metric, score) in enumerate(top_results, start=1):
            phrase = " ".join(ngram)
            if SCORING_MODE == 'leverage':
                print(f"{rank}. \"{phrase}\" (Count: {count}, MI: {metric:.1f})")
            else:
                print(f"{rank}. \"{phrase}\" (Count: {count})")

            examples = find_example_usages(ngram, all_intervals, BLACKLIST, TOP_EXTENSIONS)
            for filler, ex_count in examples:
                if ex_count > 1:
                    print(f"\t  {phrase} {filler} (x{ex_count})")
                else:
                    print(f"\t  {phrase} {filler}")

if __name__ == "__main__":
    main()
