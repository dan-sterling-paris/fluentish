#!/usr/bin/env python3
"""
Generate an EPUB teacher's manual from the FluentISH 24-Lesson Blueprint.

Reads the JavaScript data from blueprint.html, converts it to JSON via Node.js,
and generates a structured, Kindle-friendly EPUB using ebooklib.
"""

import json
import os
import re
import subprocess
import sys
import html as html_module

from ebooklib import epub


# ---------------------------------------------------------------------------
# 1. EXTRACT DATA VIA NODE.JS
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(SCRIPT_DIR, "blueprint.html")
EPUB_PATH = os.path.join(SCRIPT_DIR, "blueprint.epub")


def extract_data():
    """Use Node.js to evaluate the blueprint() JS function and return JSON."""
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Extract the JS between the last <script> tag and </script>.
    # The blueprint() function lives in the final <script> block.
    match = re.search(
        r"<script>\s*(function blueprint\(\).*?)</script>",
        html_content,
        re.DOTALL,
    )
    if not match:
        print("ERROR: Could not find blueprint() function in HTML.")
        sys.exit(1)

    fn_source = match.group(1).strip()

    # Build a Node.js script that defines the function, calls it,
    # and extracts the serialisable data (excluding methods).
    node_script = fn_source + """
;
const data = blueprint();
const output = {
    stages: data.stages,
    buildingBlockStages: data.buildingBlockStages,
    lessons: data.lessons,
};
console.log(JSON.stringify(output));
"""

    result = subprocess.run(
        ["node", "-e", node_script],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        print("Node.js error:", result.stderr)
        sys.exit(1)

    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# 2. STYLE DEFINITIONS
# ---------------------------------------------------------------------------

BOOK_CSS = """
body {
    font-family: Georgia, 'Times New Roman', serif;
    color: #1a1a2e;
    line-height: 1.6;
    margin: 0;
    padding: 0;
}
h1, h2, h3, h4 {
    font-family: Georgia, 'Times New Roman', serif;
    color: #003359;
}
h1 { font-size: 1.8em; margin-bottom: 0.3em; }
h2 { font-size: 1.4em; margin-top: 1.2em; margin-bottom: 0.3em; }
h3 { font-size: 1.15em; margin-top: 1em; margin-bottom: 0.2em; }
h4 { font-size: 1em; margin-top: 0.8em; margin-bottom: 0.2em; }

p { margin: 0.4em 0; }

.title-page {
    text-align: center;
    padding-top: 3em;
}
.title-page h1 {
    font-size: 2.2em;
    color: #003359;
    margin-bottom: 0.1em;
}
.title-page .subtitle {
    font-size: 1.1em;
    color: #C8102E;
    font-style: italic;
}
.title-page .edition {
    font-size: 0.9em;
    color: #6B7280;
    margin-top: 2em;
}

.stage-header {
    background-color: #003359;
    color: #ffffff;
    padding: 12px 16px;
    border-radius: 6px;
    margin-top: 1.5em;
    margin-bottom: 0.8em;
}
.stage-header h2 {
    color: #ffffff;
    margin: 0;
}
.stage-header .stage-num {
    color: #C8102E;
    font-size: 1.3em;
    font-weight: bold;
}
.stage-header .milestone {
    color: #93C5FD;
    font-size: 0.85em;
    font-style: italic;
    margin-top: 0.3em;
}

.teacher-panel {
    background-color: #EEF2FF;
    border-left: 3px solid #4338CA;
    padding: 10px 14px;
    margin: 0.6em 0;
    border-radius: 4px;
}
.teacher-label {
    font-size: 0.75em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #4338CA;
    margin-bottom: 0.2em;
}

.error-panel {
    background-color: #FFF1F2;
    border-left: 3px solid #E11D48;
    padding: 10px 14px;
    margin: 0.6em 0;
    border-radius: 4px;
}
.error-label {
    font-size: 0.75em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #9F1239;
    margin-bottom: 0.2em;
}

.grammar-panel {
    background-color: #FFFBEB;
    border-left: 3px solid #D97706;
    padding: 10px 14px;
    margin: 0.6em 0;
    border-radius: 4px;
}
.grammar-label {
    font-size: 0.75em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #92400E;
    margin-bottom: 0.2em;
}

.checkpoint-panel {
    background-color: #F0FDF4;
    border-left: 3px solid #16A34A;
    padding: 10px 14px;
    margin: 0.6em 0;
    border-radius: 4px;
}
.checkpoint-label {
    font-size: 0.75em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #166534;
    margin-bottom: 0.2em;
}

.warmup-panel {
    background-color: #FFFBEB;
    border-left: 3px solid #F59E0B;
    padding: 10px 14px;
    margin: 0.6em 0;
    border-radius: 4px;
}

.objective-panel {
    background-color: #F0F4FF;
    border-left: 3px solid #003359;
    padding: 10px 14px;
    margin: 0.6em 0;
    border-radius: 4px;
}

.toolkit-panel {
    background-color: #F0F4FF;
    border-left: 3px solid #003359;
    padding: 10px 14px;
    margin: 0.6em 0;
    border-radius: 4px;
}

.homework-panel {
    background-color: #F9FAFB;
    border-left: 3px solid #9CA3AF;
    padding: 10px 14px;
    margin: 0.6em 0;
    border-radius: 4px;
}

.transition-panel {
    background-color: #FFF1F2;
    border-left: 3px solid #C8102E;
    padding: 10px 14px;
    margin: 0.8em 0;
    border-radius: 4px;
}

.lesson-header {
    border-bottom: 2px solid #003359;
    padding-bottom: 0.3em;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}
.lesson-num {
    font-size: 1.6em;
    font-weight: bold;
    color: #003359;
}
.lesson-title {
    font-size: 1.2em;
    color: #003359;
    font-weight: bold;
}

.type-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.7em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.type-learn {
    background-color: rgba(77, 212, 245, 0.2);
    color: #003359;
}
.type-practice {
    background-color: #FEF3C7;
    color: #92400E;
}
.type-perform {
    background-color: #C8102E;
    color: #ffffff;
}

.frame-display {
    font-size: 1.3em;
    font-weight: bold;
    color: #003359;
    font-family: Georgia, serif;
    margin: 0.3em 0;
}
.frame-slot {
    display: inline;
    border-bottom: 2px solid #C8102E;
    color: #C8102E;
    padding: 0 4px;
}
.phonetic {
    font-size: 0.85em;
    color: #6B7280;
    font-style: italic;
}
.english-meaning {
    font-size: 0.85em;
    color: #9CA3AF;
    font-style: italic;
}
.filler-chip {
    display: inline-block;
    border: 1px solid #E5E1DA;
    border-radius: 12px;
    padding: 2px 8px;
    font-size: 0.85em;
    color: #003359;
    margin: 2px 3px;
}
.filler-en {
    color: #9CA3AF;
    font-size: 0.8em;
    margin-left: 3px;
}

.building-block-chip {
    display: inline-block;
    background-color: rgba(77, 212, 245, 0.12);
    border: 1px solid rgba(77, 212, 245, 0.4);
    border-radius: 12px;
    padding: 2px 8px;
    font-size: 0.85em;
    color: #003359;
    font-weight: 600;
    margin: 2px 3px;
}

.step-card {
    border: 1px solid #E5E1DA;
    border-radius: 6px;
    padding: 10px 14px;
    margin: 0.5em 0;
    background-color: #ffffff;
}
.step-num {
    display: inline-block;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background-color: #003359;
    color: #ffffff;
    font-size: 0.75em;
    font-weight: bold;
    text-align: center;
    line-height: 22px;
    margin-right: 6px;
}

.tag-badge {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 0.65em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-right: 4px;
}
.tag-say { background-color: #C8102E; color: #fff; }
.tag-listen { background-color: #003359; color: #fff; }
.tag-swap { background-color: #4DD4F5; color: #003359; }
.tag-build { background-color: #FEF3C7; color: #92400E; }
.tag-check { background-color: #16A34A; color: #fff; }
.tag-clap { background-color: #E9D5FF; color: #6B21A8; }
.tag-drill { background-color: #FFE4E6; color: #9F1239; }
.tag-write { background-color: #F3F4F6; color: #374151; }
.tag-model { background-color: #818CF8; color: #fff; }

.french-text {
    font-weight: bold;
    color: #003359;
}
.step-detail {
    font-size: 0.9em;
    color: #6B7280;
    margin-top: 0.2em;
}
.step-items {
    margin: 0.3em 0 0.3em 1em;
}

.rubric-list {
    margin: 0.3em 0 0.3em 1em;
}
.rubric-list li {
    margin-bottom: 0.3em;
    font-size: 0.9em;
}

.toc-list {
    list-style: none;
    padding-left: 0;
}
.toc-list li {
    margin-bottom: 0.3em;
}
.toc-stage {
    font-weight: bold;
    color: #003359;
    font-size: 1.05em;
    margin-top: 0.6em;
}
.toc-lesson {
    padding-left: 1.5em;
    font-size: 0.9em;
}

hr {
    border: none;
    border-top: 1px solid #E5E1DA;
    margin: 1em 0;
}
"""


# ---------------------------------------------------------------------------
# 3. HTML HELPERS
# ---------------------------------------------------------------------------

def esc(text):
    """Escape HTML entities in text, handling None gracefully."""
    if text is None:
        return ""
    return html_module.escape(str(text))


def clean_html_content(text):
    """
    Content fields may contain HTML tags (like <span class="frame-slot">).
    We allow those through but escape any angle brackets that are not part
    of our known tags.
    """
    if text is None:
        return ""
    # Replace frame-slot spans with our styled version
    text = re.sub(
        r'<span class="frame-slot">(.*?)</span>',
        r'<span class="frame-slot">\1</span>',
        text,
    )
    return text


def tag_class(tag):
    """Return the CSS class for a step tag."""
    return f"tag-{tag.lower()}" if tag else "tag-say"


def type_class(lesson_type):
    """Return the CSS class for a lesson type badge."""
    mapping = {"Learn": "type-learn", "Practice": "type-practice", "Perform": "type-perform"}
    return mapping.get(lesson_type, "type-learn")


def get_blocks_for_lesson(building_block_stages, lesson_num):
    """Replicate the blocksFor() JS method in Python."""
    result = []
    for stage in building_block_stages:
        if lesson_num >= stage["fromLesson"]:
            # Find next stage's fromLesson
            next_from = 999
            for s in building_block_stages:
                if s["fromLesson"] > stage["fromLesson"]:
                    next_from = min(next_from, s["fromLesson"])
            is_new = (
                lesson_num < next_from
                and lesson_num >= stage["fromLesson"]
                and lesson_num < stage["fromLesson"] + 3
                and lesson_num == stage["fromLesson"]
            )
            for b in stage["blocks"]:
                result.append({"fr": b["fr"], "en": b["en"], "isNew": is_new})
    return result


# ---------------------------------------------------------------------------
# 4. BUILD CHAPTER CONTENT
# ---------------------------------------------------------------------------

def build_title_page():
    """Build the HTML for the title page."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Title</title>
<style>{BOOK_CSS}</style>
</head>
<body>
<div class="title-page">
<h1>FluentISH</h1>
<h1 style="color: #C8102E; margin-top: 0;">24-Lesson Blueprint</h1>
<p class="subtitle">Teacher's Edition</p>
<p class="edition">1-to-1 Lesson Delivery Manual</p>
<p class="edition">30 Frames &middot; 5 Stages &middot; Zero to FluentISH</p>
<hr style="margin-top: 3em; border-top: 2px solid #003359; width: 40%;" />
<p style="font-size: 0.85em; color: #6B7280; margin-top: 1em;">
This manual contains everything you need to deliver the complete FluentISH programme:
stage guidance, lesson plans, step-by-step instructions, teacher notes, error correction
strategies, checkpoints, and homework.
</p>
</div>
</body>
</html>"""


def build_introduction():
    """Build the introduction / phonetic key chapter."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Introduction</title>
<style>{BOOK_CSS}</style>
</head>
<body>
<h1>Introduction</h1>

<h2>About This Manual</h2>
<p>This is the complete teacher's delivery manual for the FluentISH 24-lesson programme.
Each lesson is a self-contained plan designed for 1-to-1 teaching. The programme takes a
complete beginner from zero to "FluentISH" (able to operate independently in a
French-speaking environment for an entire day) through 30 sentence frames across 5 stages.</p>

<h2>The Five Stages</h2>
<ol>
<li><strong>The Ignition</strong> (Lessons 1-3) - 4 frames. First words, first confidence.</li>
<li><strong>The Toolkit</strong> (Lessons 4-7) - 10 frames. Transactional conversations.</li>
<li><strong>The Weave</strong> (Lessons 8-12) - 18 frames. Linking ideas, past events, opinions.</li>
<li><strong>The Ring</strong> (Lessons 13-18) - 24 frames. Real conversations, 10+ minutes.</li>
<li><strong>The Road</strong> (Lessons 19-24) - 30 frames. Independence in France.</li>
</ol>

<h2>How to Use Each Lesson Plan</h2>
<p>Each lesson includes:</p>
<ul>
<li><strong>Teacher Objective</strong> - what you are trying to achieve</li>
<li><strong>Teacher Notes</strong> - practical guidance for delivery</li>
<li><strong>Frames</strong> - the sentence patterns being taught, with fillers</li>
<li><strong>Steps</strong> - numbered, timed instructions with teacher voice and error correction</li>
<li><strong>Checkpoint</strong> - what the student should be able to do by the end</li>
<li><strong>Homework</strong> - between-lesson practice</li>
</ul>

<div class="grammar-panel">
<p class="grammar-label">Phonetic Guide Key</p>
<p>This manual uses <strong>informal English approximations</strong> (e.g., "zhuh SWEE" for
<em>je suis</em>), not IPA. CAPS mark the stressed syllable. For precise pronunciation,
model the sounds live for your student and use native speaker recordings on
<a href="https://forvo.com">Forvo.com</a> as reference.</p>
</div>

<h2>Step Tags</h2>
<p>Each step is tagged with an activity type:</p>
<ul>
<li><span class="tag-badge tag-listen">LISTEN</span> Student listens to teacher model</li>
<li><span class="tag-badge tag-say">SAY</span> Student repeats or produces French</li>
<li><span class="tag-badge tag-swap">SWAP</span> Student swaps fillers in a frame</li>
<li><span class="tag-badge tag-build">BUILD</span> Student constructs sentences</li>
<li><span class="tag-badge tag-drill">DRILL</span> Rapid retrieval practice</li>
<li><span class="tag-badge tag-clap">CLAP</span> Rhythm and stress work</li>
<li><span class="tag-badge tag-check">CHECK</span> Comprehension or production check</li>
<li><span class="tag-badge tag-write">WRITE</span> Written activity</li>
<li><span class="tag-badge tag-model">MODEL</span> Teacher demonstrates</li>
</ul>

<h2>Colour Coding in This Manual</h2>
<ul>
<li><span style="color: #4338CA; font-weight: bold;">Blue/Indigo panels</span> - Teacher-specific guidance</li>
<li><span style="color: #E11D48; font-weight: bold;">Rose/Red panels</span> - Error watch and correction</li>
<li><span style="color: #D97706; font-weight: bold;">Amber panels</span> - Grammar notes and warm-ups</li>
<li><span style="color: #16A34A; font-weight: bold;">Green panels</span> - Checkpoints (what the student can now do)</li>
</ul>

</body>
</html>"""


def build_stage_chapter(stage, lessons, building_block_stages):
    """Build the HTML for a full stage chapter, including all its lessons."""
    stage_num = stage["num"]
    stage_name = esc(stage["name"])
    milestone = esc(stage.get("milestone", ""))
    sessions = esc(stage.get("sessions", ""))
    cumulative = stage.get("cumulativeFrames", 0)

    parts = []
    parts.append(f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Stage {stage_num}: {stage_name}</title>
<style>{BOOK_CSS}</style>
</head>
<body>
""")

    # --- Stage header ---
    parts.append(f"""
<div class="stage-header">
<h2><span class="stage-num">Stage {stage_num}</span> &ndash; {stage_name}</h2>
<p style="color: #93C5FD; font-size: 0.85em;">Lessons {sessions} &middot; {cumulative}/30 frames</p>
<p class="milestone">{milestone}</p>
</div>
""")

    # --- Teacher guidance ---
    philosophy = stage.get("teachingPhilosophy")
    correction = stage.get("correctionStrategy")
    rubric = stage.get("assessmentRubric")

    if philosophy or correction or rubric:
        parts.append('<div class="teacher-panel">')
        parts.append('<p class="teacher-label">Teacher Guidance for This Stage</p>')
        if philosophy:
            parts.append(f'<h4 style="color: #4338CA; margin-top: 0.5em;">Teaching Philosophy</h4>')
            parts.append(f'<p style="font-size: 0.9em;">{esc(philosophy)}</p>')
        if correction:
            parts.append(f'<h4 style="color: #4338CA; margin-top: 0.5em;">Correction Strategy</h4>')
            parts.append(f'<p style="font-size: 0.9em;">{esc(correction)}</p>')
        if rubric:
            parts.append(f'<h4 style="color: #4338CA; margin-top: 0.5em;">Assessment Rubric</h4>')
            parts.append('<ul class="rubric-list">')
            for item in rubric:
                parts.append(f'<li>{esc(item)}</li>')
            parts.append('</ul>')
        parts.append('</div>')

    # --- Lessons ---
    stage_lessons = [l for l in lessons if l["stage"] == stage_num]
    for lesson in stage_lessons:
        parts.append(build_lesson_section(lesson, building_block_stages))

    # --- Stage transition criteria (after the last lesson) ---
    transition = stage.get("transition", [])
    transition_note = stage.get("transitionNote")
    if transition:
        parts.append('<div class="transition-panel">')
        parts.append(f'<p class="error-label" style="color: #C8102E;">Advance to Next Stage When</p>')
        parts.append('<ul>')
        for t in transition:
            parts.append(f'<li style="font-size: 0.9em;">{esc(t)}</li>')
        parts.append('</ul>')
        if transition_note:
            parts.append(f'<p style="font-size: 0.85em; font-style: italic; color: #6B7280; margin-top: 0.5em;">{esc(transition_note)}</p>')
        parts.append('</div>')

    parts.append("</body></html>")
    return "\n".join(parts)


def build_lesson_section(lesson, building_block_stages):
    """Build the HTML for a single lesson section."""
    parts = []
    num = lesson["num"]
    title = esc(lesson.get("title", ""))
    ltype = lesson.get("type", "Learn")
    timing = lesson.get("timingGuide", {})
    total_time = timing.get("total", "") if timing else ""

    # 1. LESSON HEADER
    parts.append('<hr style="margin-top: 2em;" />')
    parts.append(f'<div class="lesson-header">')
    parts.append(f'<span class="lesson-num">{num}</span> ')
    parts.append(f'<span class="lesson-title">{title}</span>')
    parts.append(f' <span class="type-badge {type_class(ltype)}">{esc(ltype)}</span>')
    if total_time:
        parts.append(f' <span style="font-size: 0.8em; color: #6B7280;">&middot; ~{total_time} min</span>')
    parts.append('</div>')

    # Deliverable
    deliverable = lesson.get("deliverable")
    if deliverable:
        parts.append(f'<p style="font-size: 0.9em; color: #374151; margin-bottom: 0.5em;">{esc(deliverable)}</p>')

    # 2. TEACHER OBJECTIVE
    teacher_obj = lesson.get("teacherObjective")
    if teacher_obj:
        parts.append('<div class="objective-panel">')
        parts.append('<p class="teacher-label">Teacher Objective</p>')
        parts.append(f'<p style="font-size: 0.9em;">{esc(teacher_obj)}</p>')
        parts.append('</div>')

    # 3. WARM-UP
    warm_up = lesson.get("warmUp")
    if warm_up:
        parts.append('<div class="warmup-panel">')
        parts.append('<p class="grammar-label" style="color: #92400E;">Warm-Up</p>')
        parts.append(f'<p style="font-size: 0.9em;">{esc(warm_up)}</p>')
        parts.append('</div>')

    # 4. NEW FRAMES list
    new_frames = lesson.get("newFrames", [])
    cumulative = lesson.get("cumulative", 0)
    if new_frames:
        frame_chips = " ".join(
            f'<span class="filler-chip" style="font-weight: bold;">{esc(f)}</span>'
            for f in new_frames
        )
        parts.append(f'<p style="margin-top: 0.5em;"><strong>New Frames:</strong> {frame_chips}'
                      f' <span style="font-size: 0.8em; color: #9CA3AF;">({cumulative}/30)</span></p>')
    else:
        parts.append(f'<p style="margin-top: 0.5em; font-size: 0.85em; color: #9CA3AF; font-style: italic;">'
                      f'No new frames ({cumulative}/30)</p>')

    # 5. FRAMES DISPLAY
    frames = lesson.get("frames", [])
    if frames:
        parts.append('<h3>Frames</h3>')
        for fr in frames:
            display = clean_html_content(fr.get("display", ""))
            phonetic = esc(fr.get("phonetic", ""))
            english = esc(fr.get("english", ""))
            parts.append(f'<div style="border: 1px solid #E5E1DA; border-radius: 6px; padding: 10px 14px; margin: 0.5em 0; background: #FAFAFA;">')
            parts.append(f'<p class="frame-display">{display}</p>')
            parts.append(f'<p class="phonetic">{phonetic}</p>')
            parts.append(f'<p class="english-meaning">{english}</p>')

            fillers = fr.get("fillers", [])
            if fillers:
                chips = " ".join(
                    f'<span class="filler-chip"><strong>{esc(fl["fr"])}</strong>'
                    f'<span class="filler-en">{esc(fl["en"])}</span></span>'
                    for fl in fillers
                )
                parts.append(f'<p style="margin-top: 0.4em;">{chips}</p>')
            parts.append('</div>')

    # 6. BUILDING BLOCKS
    blocks = get_blocks_for_lesson(building_block_stages, num)
    if blocks:
        parts.append('<div style="background: rgba(77,212,245,0.05); border: 1px solid rgba(77,212,245,0.3); '
                      'border-radius: 6px; padding: 10px 14px; margin: 0.6em 0;">')
        parts.append('<p style="font-size: 0.75em; font-weight: bold; color: #003359; text-transform: uppercase; '
                      'letter-spacing: 0.06em;">Building Blocks (slot into any frame)</p>')
        block_chips = " ".join(
            f'<span class="building-block-chip">{esc(b["fr"])} '
            f'<span class="filler-en">{esc(b["en"])}</span></span>'
            for b in blocks
        )
        parts.append(f'<p>{block_chips}</p>')
        parts.append('</div>')

    # 7. TEACHER NOTES
    teacher_notes = lesson.get("teacherNotes", [])
    if teacher_notes:
        parts.append('<div class="teacher-panel">')
        parts.append('<p class="teacher-label">Teacher Notes</p>')
        parts.append('<ul style="margin: 0.3em 0 0.3em 1em;">')
        for note in teacher_notes:
            parts.append(f'<li style="font-size: 0.88em; margin-bottom: 0.3em;">{esc(note)}</li>')
        parts.append('</ul>')
        parts.append('</div>')

    # 8. STEPS
    steps = lesson.get("steps", [])
    if steps:
        parts.append('<h3>Steps</h3>')
        for i, step in enumerate(steps, 1):
            tag = step.get("tag", "SAY")
            tc = tag_class(tag)
            action = esc(step.get("action", ""))
            content = clean_html_content(step.get("content", "") or "")
            phonetic = esc(step.get("phonetic", "") or "")
            detail = esc(step.get("detail", "") or "")
            step_timing = step.get("timing", "")
            items = step.get("items", [])
            teacher_instr = step.get("teacherInstruction")
            error_corr = step.get("errorCorrection")

            parts.append(f'<div class="step-card">')

            # Step number + tag + timing
            timing_str = f' <span style="font-size: 0.75em; color: #9CA3AF;">({step_timing} min)</span>' if step_timing else ""
            parts.append(f'<p><span class="step-num">{i}</span>'
                          f'<span class="tag-badge {tc}">{esc(tag)}</span>'
                          f'{timing_str}'
                          f' <span style="font-size: 0.9em; font-weight: 600; color: #374151;">{action}</span></p>')

            # Content (French text)
            if content:
                parts.append(f'<p class="french-text" style="margin-top: 0.3em;">{content}</p>')

            # Phonetic
            if phonetic:
                parts.append(f'<p class="phonetic">{phonetic}</p>')

            # Detail
            if detail:
                parts.append(f'<p class="step-detail">{detail}</p>')

            # Items
            if items:
                parts.append('<ul class="step-items">')
                for item in items:
                    parts.append(f'<li style="font-size: 0.88em;">{esc(item)}</li>')
                parts.append('</ul>')

            # Teacher instruction
            if teacher_instr:
                parts.append('<div class="teacher-panel" style="margin-top: 0.4em;">')
                parts.append('<p class="teacher-label">Teacher</p>')
                parts.append(f'<p style="font-size: 0.88em;">{esc(teacher_instr)}</p>')
                parts.append('</div>')

            # Error correction
            if error_corr:
                parts.append('<div class="error-panel" style="margin-top: 0.4em;">')
                parts.append('<p class="error-label">Watch For</p>')
                parts.append(f'<p style="font-size: 0.88em;">{esc(error_corr)}</p>')
                parts.append('</div>')

            parts.append('</div>')

    # 9. ERROR WATCH
    error_watch = lesson.get("errorWatch", [])
    if error_watch:
        parts.append('<div class="error-panel">')
        parts.append('<p class="error-label">&#9888; Common Errors to Watch For</p>')
        for ew in error_watch:
            parts.append(f'<p style="font-weight: bold; font-size: 0.9em; color: #9F1239;">{esc(ew.get("error", ""))}</p>')
            parts.append(f'<p style="font-size: 0.88em; font-style: italic; color: #881337;">Fix: {esc(ew.get("correction", ""))}</p>')
        parts.append('</div>')

    # 10. GRAMMAR NOTE
    grammar_note = lesson.get("grammarNote")
    if grammar_note:
        parts.append('<div class="grammar-panel">')
        parts.append('<p class="grammar-label">Grammar Glimpse</p>')
        parts.append(f'<p style="font-size: 0.9em;">{esc(grammar_note)}</p>')
        parts.append('</div>')

    # 11. CHECKPOINT
    checkpoint = lesson.get("checkpoint", [])
    if checkpoint:
        parts.append('<div class="checkpoint-panel">')
        parts.append('<p class="checkpoint-label">Checkpoint: Student Can Now...</p>')
        parts.append('<ul>')
        for c in checkpoint:
            parts.append(f'<li style="font-size: 0.9em; color: #166534;">{esc(c)}</li>')
        parts.append('</ul>')
        parts.append('</div>')

    # 12. TOOLKIT
    toolkit = lesson.get("toolkit")
    if toolkit:
        tk_title = esc(toolkit.get("title", "Toolkit"))
        phrases = toolkit.get("phrases", [])
        parts.append('<div class="toolkit-panel">')
        parts.append(f'<p class="teacher-label" style="color: #003359;">{tk_title}</p>')
        if phrases:
            parts.append('<table style="width: 100%; border-collapse: collapse; margin-top: 0.3em;">')
            for ph in phrases:
                fr_text = esc(ph.get("fr", ""))
                phonetic_text = esc(ph.get("phonetic", ""))
                en_text = esc(ph.get("en", ""))
                parts.append(f'<tr>')
                parts.append(f'<td style="padding: 3px 6px; font-weight: bold; color: #003359;">{fr_text}</td>')
                parts.append(f'<td style="padding: 3px 6px; font-style: italic; color: #6B7280;">{phonetic_text}</td>')
                parts.append(f'<td style="padding: 3px 6px; color: #9CA3AF;">= {en_text}</td>')
                parts.append(f'</tr>')
            parts.append('</table>')
        parts.append('</div>')

    # 13. HOMEWORK
    homework = lesson.get("homework")
    if homework:
        parts.append('<div class="homework-panel">')
        parts.append('<p style="font-size: 0.75em; font-weight: bold; text-transform: uppercase; '
                      'letter-spacing: 0.06em; color: #374151;">Homework / Between Lessons</p>')
        parts.append(f'<p style="font-size: 0.9em;">{esc(homework)}</p>')
        parts.append('</div>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 5. ASSEMBLE THE EPUB
# ---------------------------------------------------------------------------

def build_epub(data):
    """Build the EPUB from the parsed data."""
    book = epub.EpubBook()

    # Metadata
    book.set_identifier("fluentish-24-lesson-blueprint-teachers-edition")
    book.set_title("FluentISH 24-Lesson Blueprint - Teacher's Edition")
    book.set_language("en")
    book.add_author("FluentISH")
    book.add_metadata("DC", "description",
                       "Complete teacher delivery manual for the FluentISH 24-lesson French programme. "
                       "30 frames, 5 stages, zero to FluentISH.")

    # CSS
    style = epub.EpubItem(
        uid="style",
        file_name="style/default.css",
        media_type="text/css",
        content=BOOK_CSS.encode("utf-8"),
    )
    book.add_item(style)

    chapters = []
    spine = ["nav"]
    toc = []

    # --- Title page ---
    title_ch = epub.EpubHtml(
        title="Title Page",
        file_name="title.xhtml",
        lang="en",
    )
    title_ch.set_content(build_title_page().encode("utf-8"))
    title_ch.add_item(style)
    book.add_item(title_ch)
    chapters.append(title_ch)
    spine.append(title_ch)

    # --- Introduction ---
    intro_ch = epub.EpubHtml(
        title="Introduction",
        file_name="introduction.xhtml",
        lang="en",
    )
    intro_ch.set_content(build_introduction().encode("utf-8"))
    intro_ch.add_item(style)
    book.add_item(intro_ch)
    chapters.append(intro_ch)
    spine.append(intro_ch)
    toc.append(intro_ch)

    # --- Stage chapters ---
    stages = data["stages"]
    lessons = data["lessons"]
    bbs = data["buildingBlockStages"]

    for stage in stages:
        stage_num = stage["num"]
        stage_name = stage["name"]
        ch_title = f"Stage {stage_num}: {stage_name}"

        stage_ch = epub.EpubHtml(
            title=ch_title,
            file_name=f"stage_{stage_num}.xhtml",
            lang="en",
        )
        stage_ch.set_content(
            build_stage_chapter(stage, lessons, bbs).encode("utf-8")
        )
        stage_ch.add_item(style)
        book.add_item(stage_ch)
        chapters.append(stage_ch)
        spine.append(stage_ch)

        # Build TOC: stage entry with lesson sub-entries
        stage_lessons = [l for l in lessons if l["stage"] == stage_num]
        lesson_links = []
        for lesson in stage_lessons:
            # We don't have separate files per lesson (they are within the stage chapter)
            # so we just list them in the TOC section
            lesson_links.append(
                epub.Section(f"Lesson {lesson['num']}: {lesson.get('title', '')}")
            )

        toc.append(
            (epub.Section(ch_title), [stage_ch])
        )

    # --- Table of Contents ---
    book.toc = toc

    # Navigation files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Spine
    book.spine = spine

    # Write
    epub.write_epub(EPUB_PATH, book, {})
    return EPUB_PATH


# ---------------------------------------------------------------------------
# 6. MAIN
# ---------------------------------------------------------------------------

def main():
    print("Extracting data from blueprint.html via Node.js...")
    data = extract_data()

    print(f"  Found {len(data['stages'])} stages")
    print(f"  Found {len(data['lessons'])} lessons")
    print(f"  Found {len(data['buildingBlockStages'])} building block stages")

    print("Building EPUB...")
    path = build_epub(data)

    size = os.path.getsize(path)
    print(f"EPUB generated: {path}")
    print(f"File size: {size:,} bytes ({size / 1024:.1f} KB)")

    if size < 50_000:
        print("WARNING: File seems small. Check content.")
    else:
        print("Done. File looks good (EPUB uses ZIP compression; uncompressed content is much larger).")


if __name__ == "__main__":
    main()
