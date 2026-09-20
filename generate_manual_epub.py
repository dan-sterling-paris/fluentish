#!/usr/bin/env python3
"""
Generate a full scripted teaching manual EPUB from the FluentISH Blueprint.

This produces a prose-heavy, lesson-by-lesson manual where each lesson is
3-5 pages of detailed teacher guidance: what to say, what to do, sample
dialogues, transitions, troubleshooting, and rationale.
"""

import json
import os
import re
import subprocess
import sys
import textwrap

from ebooklib import epub

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(SCRIPT_DIR, "blueprint.html")
EPUB_PATH = os.path.join(SCRIPT_DIR, "fluentish-teaching-manual.epub")


# ---------------------------------------------------------------------------
# 1. EXTRACT DATA VIA NODE.JS
# ---------------------------------------------------------------------------

def extract_data():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()

    match = re.search(
        r"<script>\s*(function blueprint\(\).*?)</script>",
        html_content,
        re.DOTALL,
    )
    if not match:
        print("ERROR: Could not find blueprint() function in HTML.")
        sys.exit(1)

    fn_source = match.group(1).strip()

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
# 2. STYLE
# ---------------------------------------------------------------------------

BOOK_CSS = """
body {
    font-family: Georgia, 'Times New Roman', serif;
    color: #1a1a2e;
    line-height: 1.7;
    margin: 0;
    padding: 0;
}
h1, h2, h3, h4 {
    font-family: Georgia, 'Times New Roman', serif;
    color: #003359;
    page-break-after: avoid;
}
h1 { font-size: 1.8em; margin-bottom: 0.3em; }
h2 { font-size: 1.4em; margin-top: 1.5em; margin-bottom: 0.4em; }
h3 { font-size: 1.15em; margin-top: 1.2em; margin-bottom: 0.3em; color: #003359; }
h4 { font-size: 1em; margin-top: 0.8em; margin-bottom: 0.2em; }

p { margin: 0.5em 0; }

.title-page {
    text-align: center;
    padding-top: 4em;
}
.title-page h1 {
    font-size: 2.2em;
    color: #003359;
    margin-bottom: 0.1em;
}
.title-page .subtitle {
    font-size: 1.2em;
    color: #C8102E;
    font-style: italic;
}
.title-page .edition {
    font-size: 0.9em;
    color: #6B7280;
    margin-top: 2em;
}

/* Panels */
.teacher-box {
    background-color: #EEF2FF;
    border-left: 3px solid #4338CA;
    padding: 10px 14px;
    margin: 0.8em 0;
    border-radius: 4px;
}
.error-box {
    background-color: #FFF1F2;
    border-left: 3px solid #E11D48;
    padding: 10px 14px;
    margin: 0.8em 0;
    border-radius: 4px;
}
.grammar-box {
    background-color: #FFFBEB;
    border-left: 3px solid #D97706;
    padding: 10px 14px;
    margin: 0.8em 0;
    border-radius: 4px;
}
.checkpoint-box {
    background-color: #F0FDF4;
    border-left: 3px solid #16A34A;
    padding: 10px 14px;
    margin: 0.8em 0;
    border-radius: 4px;
}
.warmup-box {
    background-color: #FFFBEB;
    border-left: 3px solid #F59E0B;
    padding: 10px 14px;
    margin: 0.8em 0;
    border-radius: 4px;
}
.homework-box {
    background-color: #F9FAFB;
    border-left: 3px solid #6B7280;
    padding: 10px 14px;
    margin: 0.8em 0;
    border-radius: 4px;
}
.frame-box {
    background-color: #F8FAFC;
    border: 1px solid #CBD5E1;
    padding: 12px 16px;
    margin: 0.8em 0;
    border-radius: 6px;
}
.dialogue-box {
    background-color: #FAFAFA;
    border-left: 3px solid #003359;
    padding: 10px 14px;
    margin: 0.8em 0;
    font-size: 0.95em;
}

/* Inline styles */
.french { font-weight: bold; color: #003359; }
.phonetic { font-style: italic; color: #6B7280; font-size: 0.9em; }
.english { color: #9CA3AF; font-style: italic; font-size: 0.9em; }
.label { font-size: 0.75em; font-weight: bold; text-transform: uppercase; letter-spacing: 0.08em; }
.label-teacher { color: #4338CA; }
.label-error { color: #E11D48; }
.label-grammar { color: #D97706; }
.label-checkpoint { color: #16A34A; }
.label-warmup { color: #D97706; }
.label-homework { color: #6B7280; }

.tag {
    display: inline-block;
    font-size: 0.7em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 1px 6px;
    border-radius: 3px;
    color: #fff;
}
.tag-say { background-color: #C8102E; }
.tag-listen { background-color: #003359; }
.tag-swap { background-color: #4DD4F5; color: #003359; }
.tag-build { background-color: #FEF3C7; color: #92400E; }
.tag-check { background-color: #16A34A; }
.tag-clap { background-color: #E9D5FF; color: #6B21A8; }
.tag-drill { background-color: #FFE4E6; color: #9F1239; }
.tag-write { background-color: #F3F4F6; color: #374151; }
.tag-model { background-color: #818CF8; }

.step-num {
    display: inline-block;
    width: 22px; height: 22px;
    border-radius: 50%;
    background-color: #003359;
    color: #fff;
    text-align: center;
    font-size: 0.75em;
    font-weight: bold;
    line-height: 22px;
    margin-right: 6px;
}

.filler-list {
    margin: 0.4em 0;
    padding-left: 0;
    list-style: none;
}
.filler-list li {
    display: inline-block;
    background: #fff;
    border: 1px solid #E5E1DA;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 0.85em;
    margin: 2px 3px;
}

.stage-banner {
    background-color: #003359;
    color: #ffffff;
    padding: 14px 18px;
    border-radius: 6px;
    margin-bottom: 1em;
}
.stage-banner h2 { color: #fff; margin: 0; }
.stage-num { color: #C8102E; }
.milestone { color: #93C5FD; font-style: italic; font-size: 0.9em; }
.transition-box {
    background-color: #F7F4EF;
    border: 1px solid #E5E1DA;
    padding: 10px 14px;
    margin: 0.8em 0;
    border-radius: 4px;
}

hr { border: none; border-top: 1px solid #E5E1DA; margin: 1.5em 0; }
"""


# ---------------------------------------------------------------------------
# 3. CONTENT GENERATION HELPERS
# ---------------------------------------------------------------------------

def strip_html(text):
    """Remove HTML tags from a string."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", str(text))


def clean_display(display_text):
    """Convert frame display HTML to readable text, replacing slots with ___."""
    if not display_text:
        return ""
    text = re.sub(r'<span class="frame-slot">([^<]*)</span>', r"\1", display_text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def fillers_html(fillers):
    """Render filler chips as a list."""
    if not fillers:
        return ""
    items = []
    for f in fillers:
        items.append(f'<li><span class="french">{f["fr"]}</span> <span class="english">({f["en"]})</span></li>')
    return f'<ul class="filler-list">{"".join(items)}</ul>'


def tag_class(tag_name):
    """Return CSS class for a step tag."""
    t = tag_name.lower().strip()
    return f"tag-{t}" if t in ("say", "listen", "swap", "build", "check", "clap", "drill", "write", "model") else "tag-say"


def get_blocks_for(lesson_num, building_block_stages):
    """Get building blocks available for a given lesson number."""
    result = []
    for stage in building_block_stages:
        if lesson_num >= stage["fromLesson"]:
            is_new = lesson_num == stage["fromLesson"]
            for b in stage["blocks"]:
                result.append({"fr": b["fr"], "en": b["en"], "isNew": is_new})
    return result


# ---------------------------------------------------------------------------
# 4. PROSE LESSON GENERATION
# ---------------------------------------------------------------------------

def generate_lesson_chapter(lesson, stage, building_block_stages, all_lessons):
    """Generate a full prose chapter for a single lesson."""

    num = lesson["num"]
    title = lesson["title"]
    ltype = lesson["type"]
    deliverable = lesson.get("deliverable", "")
    objective = lesson.get("teacherObjective", "")
    warmup = lesson.get("warmUp", "")
    teacher_notes = lesson.get("teacherNotes", [])
    error_watch = lesson.get("errorWatch", [])
    homework = lesson.get("homework", "")
    timing = lesson.get("timingGuide", {}).get("total", 50)
    grammar_note = lesson.get("grammarNote")
    frames = lesson.get("frames", [])
    steps = lesson.get("steps", [])
    checkpoint = lesson.get("checkpoint", [])
    toolkit = lesson.get("toolkit")
    new_frames = lesson.get("newFrames", [])
    cumulative = lesson.get("cumulative", 0)

    blocks = get_blocks_for(num, building_block_stages)
    new_blocks = [b for b in blocks if b["isNew"]]

    html = []

    # ---- LESSON HEADER ----
    html.append(f'<h2>Lesson {num}: {title}</h2>')
    html.append(f'<p><span class="tag tag-{ltype.lower()}" style="font-size:0.8em; padding:2px 8px;">{ltype}</span> &nbsp; Approx. {timing} minutes</p>')

    if new_frames:
        frames_str = ", ".join([f'<span class="french">{f}</span>' for f in new_frames])
        html.append(f'<p>New frames: {frames_str} &nbsp; <span class="english">({cumulative}/30 total)</span></p>')
    else:
        html.append(f'<p>No new frames this lesson. <span class="english">({cumulative}/30 total)</span></p>')

    html.append(f'<p><strong>By the end of this lesson:</strong> {deliverable}</p>')

    # ---- TEACHER OBJECTIVE ----
    if objective:
        html.append('<div class="teacher-box">')
        html.append('<p class="label label-teacher">Your Objective</p>')
        html.append(f'<p>{objective}</p>')
        html.append('</div>')

    # ---- OPENING THE LESSON ----
    html.append('<h3>Opening the Lesson</h3>')
    if warmup:
        html.append('<div class="warmup-box">')
        html.append('<p class="label label-warmup">Warm-Up (3 minutes)</p>')
        html.append(f'<p>{warmup}</p>')
        html.append('</div>')

    if num == 1:
        html.append('<p>This is the student\'s first lesson. Begin by setting expectations: this is not a grammar class. There will be no conjugation tables, no verb lists, no textbook exercises. Instead, you are going to give them a small number of powerful sentence patterns (frames) and fill them with real words from their life. By the end of today, they will be able to say five sentences about themselves in French, from memory, and it will sound like French.</p>')
        html.append('<p>Ask them: "What do you want French for?" Listen carefully. Their answer will shape how you personalise the frames throughout the course. A student who wants to order food in Paris needs different fillers than one who wants to chat with their French partner\'s family.</p>')
    elif num <= 3:
        html.append(f'<p>Open by reviewing the frames from previous lessons. Say the frame stem and let the student complete it. For example, say "je suis..." and wait. If they complete it instantly, move on. If they hesitate, model a completion and have them repeat, then try again with a different filler. Spend no more than 3 minutes on this. The goal is activation, not perfection.</p>')
    elif num <= 7:
        html.append(f'<p>The warm-up is now a structured frame sprint. You have {cumulative - len(new_frames)} frames in play. Cycle through them rapidly: say the stem, student completes it. Mix the order. After 3 minutes, note which frames are automatic (under 2 seconds) and which still need prompting. The slow ones get extra attention today.</p>')
    elif num <= 12:
        html.append(f'<p>By now the student has {cumulative - len(new_frames)} frames. The warm-up should feel like a conversation, not a drill. Ask a question that requires a frame to answer: "What did you do yesterday?" (triggers past tense frames). "What do you think about...?" (triggers opinion frames). If the student answers in single frames, push for connected speech: "And then? Why? What happened next?"</p>')
    elif num <= 18:
        html.append(f'<p>Open with 2-3 minutes of free conversation in French. Ask about their week, their homework, something in the news. Do not correct during the warm-up. This is a confidence builder. Note any recurring errors silently for later. Then transition: "Today we are going to work on..."</p>')
    else:
        html.append(f'<p>At this stage, the warm-up IS French. Greet the student in French. Ask how they are in French. Chat for 2-3 minutes about whatever comes naturally. The student should not even notice the "lesson" has started. Then transition into the day\'s scenario or activity.</p>')

    # ---- TEACHER NOTES ----
    if teacher_notes:
        html.append('<h3>Teacher Notes</h3>')
        html.append('<div class="teacher-box">')
        html.append('<p class="label label-teacher">Before You Begin</p>')
        for note in teacher_notes:
            html.append(f'<p>&#8250; {note}</p>')
        html.append('</div>')

    # ---- FRAMES ----
    if frames:
        html.append('<h3>Today\'s Frames</h3>')
        if len(frames) == 1:
            html.append(f'<p>This lesson introduces one new frame. Present it to the student as shown below. Say it naturally three times before asking the student to repeat.</p>')
        elif len(frames) > 1:
            html.append(f'<p>This lesson introduces {len(frames)} new frames. Present each one separately. Model each frame three times at natural speed before the student attempts it.</p>')

        for frame in frames:
            display = clean_display(frame.get("display", ""))
            phonetic = frame.get("phonetic", "")
            english = frame.get("english", "")
            fillers = frame.get("fillers", [])

            html.append('<div class="frame-box">')
            html.append(f'<p style="font-size:1.3em;"><span class="french">{display}</span></p>')
            html.append(f'<p class="phonetic">{phonetic}</p>')
            html.append(f'<p class="english">{english}</p>')

            if fillers:
                html.append(f'<p style="margin-top:0.5em;"><strong>Fillers to teach:</strong></p>')
                html.append(fillers_html(fillers))
            html.append('</div>')

            html.append(f'<p>Say "<span class="french">{display}</span>" three times, completing it with different fillers each time. Then say just the stem ("<span class="french">{display.split("___")[0].strip() if "___" in display else display}</span>...") and pause. The student should complete it. If they freeze, give the first syllable of a filler as a prompt, not the whole word.</p>')

    # ---- BUILDING BLOCKS ----
    if new_blocks:
        html.append('<h3>New Building Blocks</h3>')
        html.append('<p>Building blocks are portable modifiers that slot into any frame. Introduce these casually during the lesson. The student does not need to memorise them now; they will absorb them through repeated exposure.</p>')
        for b in new_blocks:
            html.append(f'<p>&#8226; <span class="french">{b["fr"]}</span> <span class="english">({b["en"]})</span></p>')

    # ---- GRAMMAR NOTE ----
    if grammar_note:
        html.append('<div class="grammar-box">')
        html.append('<p class="label label-grammar">Grammar Glimpse</p>')
        html.append(f'<p>{grammar_note}</p>')
        html.append('<p><em>You do not need to teach this explicitly. It is here so you understand the pattern. If the student asks "why?", you have the answer. Otherwise, let the frames do the work.</em></p>')
        html.append('</div>')

    # ---- STEP-BY-STEP LESSON DELIVERY ----
    html.append('<h3>Step-by-Step Lesson Delivery</h3>')

    for i, step in enumerate(steps):
        tag = step.get("tag", "")
        tag_cls = tag_class(tag)
        action = step.get("action", "")
        content = step.get("content", "")
        phonetic = step.get("phonetic", "")
        detail = step.get("detail", "")
        items = step.get("items", [])
        t_instruction = step.get("teacherInstruction", "")
        e_correction = step.get("errorCorrection", "")
        step_timing = step.get("timing", "")

        timing_str = f" ({step_timing} min)" if step_timing else ""

        html.append(f'<h4><span class="step-num">{i+1}</span> <span class="tag {tag_cls}">{tag}</span>{timing_str}</h4>')

        # Action (what the teacher does)
        html.append(f'<p><strong>{action}</strong></p>')

        # French content
        if content:
            clean_content = strip_html(content).replace("&nbsp;", " ").replace("&rarr;", "->")
            html.append(f'<p class="french" style="font-size:1.05em;">{content}</p>')

        if phonetic:
            html.append(f'<p class="phonetic">{phonetic}</p>')

        # Detail / explanation
        if detail:
            html.append(f'<p>{detail}</p>')

        # Items
        if items:
            html.append('<ul>')
            for item in items:
                html.append(f'<li>{item}</li>')
            html.append('</ul>')

        # Teacher instruction
        if t_instruction:
            html.append('<div class="teacher-box">')
            html.append('<p class="label label-teacher">How to Deliver This</p>')
            html.append(f'<p>{t_instruction}</p>')
            html.append('</div>')

        # Error correction
        if e_correction:
            html.append('<div class="error-box">')
            html.append('<p class="label label-error">Watch For</p>')
            html.append(f'<p>{e_correction}</p>')
            html.append('</div>')

        # Add a transition note between steps
        if i < len(steps) - 1:
            html.append('<hr style="border-top: 1px dashed #E5E1DA; margin: 0.8em 0;">')

    # ---- ERROR WATCH SUMMARY ----
    if error_watch:
        html.append('<h3>Common Errors to Watch For</h3>')
        html.append('<p>These are the errors you are most likely to encounter in this lesson. Do not try to fix them all at once. Pick the most important one and address it through recasting (Stage 1-2) or elicitation (Stage 3+).</p>')
        for ew in error_watch:
            html.append('<div class="error-box">')
            html.append(f'<p><strong>{ew["error"]}</strong></p>')
            html.append(f'<p><em>Fix:</em> {ew["correction"]}</p>')
            html.append('</div>')

    # ---- CHECKPOINT ----
    if checkpoint:
        html.append('<h3>Checkpoint</h3>')
        html.append('<p>Before moving on, verify that the student can do the following. These are not tests; they are observations you make during the lesson. If the student cannot do 2 or more of these, spend the next lesson revisiting this material before introducing new frames.</p>')
        html.append('<div class="checkpoint-box">')
        html.append('<p class="label label-checkpoint">Student can now:</p>')
        for c in checkpoint:
            html.append(f'<p>&#9744; {c}</p>')
        html.append('</div>')

    # ---- TOOLKIT ----
    if toolkit:
        html.append(f'<h3>{toolkit.get("title", "Toolkit")}</h3>')
        html.append('<p>These phrases should be drilled until they are automatic. The student should produce them as reactions, not from conscious memory.</p>')
        for phrase in toolkit.get("phrases", []):
            html.append(f'<p><span class="french">{phrase["fr"]}</span> &nbsp; <span class="phonetic">{phrase["phonetic"]}</span> &nbsp; <span class="english">= {phrase["en"]}</span></p>')

    # ---- CLOSING THE LESSON ----
    html.append('<h3>Closing the Lesson</h3>')
    if num <= 3:
        html.append('<p>End with a confidence builder. Ask the student to say their best sentence from today\'s lesson. Just one, their favourite. Then tell them: that is real French. If they said it to a French person, that person would understand them. That is the standard: not perfect, not complete, just understood.</p>')
    elif num <= 7:
        html.append('<p>Close by asking the student to use three different frames in one short sequence. It does not need to be a story, just three connected sentences. This tests whether the frames are available for retrieval, not just recognition. Praise whatever they produce.</p>')
    elif num <= 12:
        html.append('<p>End by asking: "Tell me one thing that happened today, in French." The student should produce at least 2-3 connected sentences. If they use connectors (du coup, parce que) without being prompted, note it as a win. If they default to single-frame answers, gently push: "Et du coup...?"</p>')
    elif num <= 18:
        html.append('<p>Close with a 2-minute free conversation on any topic. Do not correct. Do not teach. Just talk. This is the student\'s chance to feel like a French speaker, not a French learner. Note their strongest and weakest frames silently. Address the weakest in the debrief or next lesson.</p>')
    else:
        html.append('<p>End the lesson by asking the student what they want to practise next time. At this stage, they should be driving the curriculum. Their answer tells you what vocabulary and scenarios to prepare. If they say "I don\'t know", suggest a real-world scenario they are likely to face soon.</p>')

    # ---- HOMEWORK ----
    if homework:
        html.append('<div class="homework-box">')
        html.append('<p class="label label-homework">Homework</p>')
        html.append(f'<p>{homework}</p>')
        html.append('</div>')

    return "\n".join(html)


def generate_stage_intro(stage):
    """Generate the stage overview page."""
    html = []

    html.append(f'<div class="stage-banner">')
    html.append(f'<h2><span class="stage-num">Stage {stage["num"]}</span> &mdash; {stage["name"]}</h2>')
    html.append(f'<p>Lessons {stage["sessions"]} &nbsp;|&nbsp; {stage["cumulativeFrames"]}/30 frames</p>')
    html.append(f'<p class="milestone">{stage["milestone"]}</p>')
    html.append('</div>')

    # Teaching philosophy
    philosophy = stage.get("teachingPhilosophy", "")
    correction = stage.get("correctionStrategy", "")
    rubric = stage.get("assessmentRubric", [])

    if philosophy:
        html.append('<h3>Teaching Philosophy</h3>')
        html.append(f'<p>{philosophy}</p>')

    if correction:
        html.append('<h3>Correction Strategy</h3>')
        html.append('<div class="teacher-box">')
        html.append(f'<p>{correction}</p>')
        html.append('</div>')

    if rubric:
        html.append('<h3>Assessment Rubric</h3>')
        html.append('<p>Use these criteria to assess whether the student is ready to move to the next stage:</p>')
        for r in rubric:
            html.append(f'<p>&#9632; {r}</p>')

    return "\n".join(html)


def generate_stage_transition(stage):
    """Generate the transition criteria at the end of a stage."""
    html = []
    transition = stage.get("transition", [])
    note = stage.get("transitionNote", "")

    html.append('<div class="transition-box">')
    html.append(f'<p class="label" style="color:#C8102E;">Advance to Stage {stage["num"] + 1} When</p>')
    for t in transition:
        html.append(f'<p>&#9632; {t}</p>')
    if note:
        html.append(f'<p style="margin-top:0.5em; font-style:italic; color:#6B7280;">{note}</p>')
    html.append('</div>')

    return "\n".join(html)


# ---------------------------------------------------------------------------
# 5. COURSE OVERVIEW CHAPTER
# ---------------------------------------------------------------------------

def generate_course_overview(data):
    """Generate a high-level overview chapter showing what is taught and how."""
    stages = data["stages"]
    lessons = data["lessons"]
    bbs = data.get("buildingBlockStages", [])

    html = []

    html.append('<h1>Course Overview</h1>')

    # ---- THE BIG PICTURE ----
    html.append('<h2>The Big Picture</h2>')
    html.append('<p>This course takes an adult learner from zero spoken French to sustained, natural-sounding conversation in 24 lessons. It does not teach grammar rules, conjugation tables, or written French. It teaches the student to <em>speak</em>, using the same patterns that native French speakers rely on in everyday conversation.</p>')

    html.append('<p>The method rests on three principles:</p>')
    html.append('<ol>')
    html.append('<li><strong>Frames before grammar.</strong> Instead of learning rules and then trying to apply them, the student memorises high-frequency sentence patterns ("frames") with a variable slot. "Je suis ___" is a frame. The student fills the slot with real words from their life. Grammar is absorbed implicitly through the patterns, not taught explicitly.</li>')
    html.append('<li><strong>Production from day one.</strong> The student speaks French in the first five minutes of Lesson 1. There is no silent period, no "listen for three weeks first". The research is clear: producing output forces the brain to process language differently from merely hearing it (Swain, 1995). The student will make errors. That is expected and productive.</li>')
    html.append('<li><strong>Sound before words.</strong> Before the student learns a single sentence, they learn the three sounds that make French sound like French: the nasal vowels, the uvular R, and final-syllable stress. Getting these right early means everything that follows sounds French, not English with French vocabulary.</li>')
    html.append('</ol>')

    # ---- WHAT THE STUDENT WILL LEARN ----
    html.append('<h2>What the Student Will Learn</h2>')
    html.append('<p>By the end of 24 lessons, the student will have:</p>')
    html.append('<ul>')
    html.append('<li><strong>30 sentence frames</strong> covering self-introduction, description, asking, ordering, expressing uncertainty, modals (can/want/must/will), questions, opinions, past tense, narrative, connectors, disagreement, emphasis, duration, register variation, and problem resolution</li>')
    html.append('<li><strong>12 portable building blocks</strong> (adverbs and modifiers that slot into any frame: "un peu", "aussi", "en fait", "surtout", "peut-être", etc.)</li>')
    html.append('<li><strong>A Natural Sound Kit</strong> of discourse markers and fillers ("Ah bon?", "Exactement!", "Alors...", "Du coup...") that make them sound like a participant in conversation, not a reciter of phrases</li>')
    html.append('<li><strong>Register awareness</strong> (the difference between textbook "je ne sais pas" and real Parisian "chais pas")</li>')
    html.append('<li><strong>Recovery strategies</strong> for when they do not understand, cannot find a word, or lose their place in a conversation</li>')
    html.append('</ul>')

    # ---- THE 30 FRAMES AT A GLANCE ----
    html.append('<h2>The 30 Frames at a Glance</h2>')
    html.append('<p>Here is every frame the student will learn, in the order they are introduced. Each frame is a reusable sentence pattern with a variable slot (___) that the student fills with their own vocabulary.</p>')

    html.append('<table style="width:100%; border-collapse:collapse; font-size:0.9em;">')
    html.append('<tr style="background-color:#003359; color:#fff;"><th style="padding:6px 10px; text-align:left;">Lesson</th><th style="padding:6px 10px; text-align:left;">Frame</th><th style="padding:6px 10px; text-align:left;">English</th><th style="padding:6px 10px; text-align:left;">Stage</th></tr>')

    row_bg = False
    for lesson in lessons:
        frames = lesson.get("frames", [])
        for frame in frames:
            display = clean_display(frame.get("display", ""))
            english = frame.get("english", "")
            stage_num = lesson["stage"]
            stage_name = next((s["name"] for s in stages if s["num"] == stage_num), "")
            bg = "#F8FAFC" if row_bg else "#FFFFFF"
            html.append(f'<tr style="background-color:{bg};"><td style="padding:4px 10px; border-bottom:1px solid #E5E1DA;">{lesson["num"]}</td><td style="padding:4px 10px; border-bottom:1px solid #E5E1DA;"><span class="french">{display}</span></td><td style="padding:4px 10px; border-bottom:1px solid #E5E1DA; color:#6B7280; font-style:italic;">{english}</td><td style="padding:4px 10px; border-bottom:1px solid #E5E1DA; font-size:0.85em;">{stage_name}</td></tr>')
            row_bg = not row_bg

    html.append('</table>')

    # ---- HOW THE COURSE IS STRUCTURED ----
    html.append('<h2>How the Course Is Structured</h2>')
    html.append('<p>The 24 lessons are grouped into five stages. Each stage has a distinct teaching approach, correction strategy, and milestone. The student does not move to the next stage until they meet the transition criteria.</p>')

    for stage in stages:
        stage_lessons = [l for l in lessons if l["stage"] == stage["num"]]

        html.append(f'<h3>Stage {stage["num"]}: {stage["name"]} (Lessons {stage["sessions"]})</h3>')
        html.append(f'<p><strong>Milestone:</strong> {stage["milestone"]}</p>')
        html.append(f'<p><strong>Frames by end of stage:</strong> {stage["cumulativeFrames"]}/30</p>')

        philosophy = stage.get("teachingPhilosophy", "")
        if philosophy:
            html.append(f'<p><strong>Your role:</strong> {philosophy}</p>')

        html.append('<p><strong>Lessons in this stage:</strong></p>')
        html.append('<ul>')
        for l in stage_lessons:
            ltype = l["type"]
            new_frames = l.get("newFrames", [])
            frames_str = ", ".join(new_frames) if new_frames else "no new frames (consolidation)"
            html.append(f'<li><strong>Lesson {l["num"]}: {l["title"]}</strong> ({ltype}) - {frames_str}</li>')
        html.append('</ul>')

        transition = stage.get("transition", [])
        if transition:
            html.append('<div class="checkpoint-box">')
            html.append(f'<p class="label label-checkpoint">Advance to {"Stage " + str(stage["num"]+1) if stage["num"] < 5 else "Freestyle"} when:</p>')
            for t in transition:
                html.append(f'<p>&#9744; {t}</p>')
            html.append('</div>')

    # ---- THE THREE LESSON TYPES ----
    html.append('<h2>The Three Lesson Types</h2>')
    html.append('<p>Each lesson is labelled as one of three types. The type tells you the overall shape of the lesson and how to allocate your time.</p>')

    html.append('<h3>Learn</h3>')
    html.append('<p>A Learn lesson introduces new frames. The bulk of the time is spent on modelling, repetition, and controlled practice. You lead. The student follows, then gradually takes over. Expect to do more talking than the student in the first half, and less in the second half. Most lessons in Stages 1-3 are Learn lessons.</p>')

    html.append('<h3>Practice</h3>')
    html.append('<p>A Practice lesson may introduce one frame, but the focus is on combining multiple frames in realistic scenarios. The student does most of the talking. You set up situations, play roles, and push for connected speech. Correct sparingly. The goal is integration, not perfection.</p>')

    html.append('<h3>Perform</h3>')
    html.append('<p>A Perform lesson introduces no new frames (or at most one). It is an extended, realistic scenario where the student uses everything they know. You play the role of a French speaker (waiter, receptionist, stranger) and do not break character. Do not correct during the performance. Debrief afterwards. Perform lessons are the student\'s chance to feel what real French conversation is like.</p>')

    # ---- THE BUILDING BLOCKS ----
    html.append('<h2>Building Blocks</h2>')
    html.append('<p>Building blocks are portable modifiers that slot into any frame. They are introduced gradually across the course. Unlike frames, they are not drilled explicitly; they are woven into activities and absorbed through repetition.</p>')

    html.append('<table style="width:100%; border-collapse:collapse; font-size:0.9em;">')
    html.append('<tr style="background-color:#003359; color:#fff;"><th style="padding:6px 10px; text-align:left;">Introduced</th><th style="padding:6px 10px; text-align:left;">Block</th><th style="padding:6px 10px; text-align:left;">English</th></tr>')

    row_bg = False
    for bb_stage in bbs:
        for b in bb_stage["blocks"]:
            bg = "#F8FAFC" if row_bg else "#FFFFFF"
            html.append(f'<tr style="background-color:{bg};"><td style="padding:4px 10px; border-bottom:1px solid #E5E1DA;">Lesson {bb_stage["fromLesson"]}</td><td style="padding:4px 10px; border-bottom:1px solid #E5E1DA;"><span class="french">{b["fr"]}</span></td><td style="padding:4px 10px; border-bottom:1px solid #E5E1DA; color:#6B7280; font-style:italic;">{b["en"]}</td></tr>')
            row_bg = not row_bg
    html.append('</table>')

    # ---- THE STUDENT'S JOURNEY ----
    html.append('<h2>The Student\'s Journey</h2>')
    html.append('<p>Here is what the student\'s experience looks like, lesson by lesson. Use this as a quick reference to see where any individual lesson fits in the bigger picture.</p>')

    html.append('<p><strong>Lessons 1-3 (The Ignition):</strong> The student arrives knowing nothing. They leave able to introduce themselves, describe their surroundings, ask for things, and perform a rehearsed cafe dialogue. They have 4 frames and a set of survival phrases. The critical achievement is not vocabulary; it is the realisation that they can produce French that a native speaker would understand.</p>')

    html.append('<p><strong>Lessons 4-7 (The Toolkit):</strong> The student now has tools for uncertainty ("je sais pas"), desire and ability ("je veux/peux/dois/vais"), questions ("est-ce que"), and opinions ("je trouve ça", "c\'est"). The Beermat grid (4 modals x unlimited verbs) is the single biggest productivity unlock. By Lesson 7, they can sustain a 2-minute transactional conversation with no English.</p>')

    html.append('<p><strong>Lessons 8-12 (The Weave):</strong> Past tense, connectors, opinions with reasons, and storytelling. This is where French becomes personal. The student tells real stories from their life. Sentences become multi-clause. The 5-minute conversation barrier is broken. This is also where the emotional connection to the language often forms.</p>')

    html.append('<p><strong>Lessons 13-18 (The Ring):</strong> Disagreement, emphasis, register variation, and extended conversation. The student learns to push back ("en fait"), express personality ("moi je suis"), and navigate disruption without freezing. They discover Parisian French (chais pas, y a, bah oui). By Lesson 18, they sustain 15 minutes of conversation.</p>')

    html.append('<p><strong>Lessons 19-24 (The Road):</strong> Full-day simulations, phone calls, problem resolution, and the 5-minute life story. The student navigates a complete day in France using all 30 frames. They make a phone reservation, resolve a complaint, and tell the story of their life in French. The final lesson is a debrief of a real-world French interaction. They are FluentISH.</p>')

    # ---- KEY PRINCIPLES TO KEEP IN MIND ----
    html.append('<h2>Key Principles to Keep in Mind</h2>')

    html.append('<h3>Personalise everything</h3>')
    html.append('<p>The frames are the skeleton; the student\'s own vocabulary is the muscle. "Je suis ___" is useful. "Je suis ingénieur à Manchester" is personal and memorable. Every frame should be filled with words from the student\'s real life: their job, their city, their interests, their upcoming trip. If a filler does not connect to their world, swap it for one that does.</p>')

    html.append('<h3>Speed over accuracy</h3>')
    html.append('<p>Fluency is about retrieval speed, not grammatical perfection. A student who says "je veux manger" instantly is more communicatively competent than one who pauses for ten seconds and then says "je voudrais manger, s\'il vous plaît". Drills should be fast. Hesitation is the enemy, not errors. Errors will self-correct over time as the frames become automatic. Hesitation will not.</p>')

    html.append('<h3>The spiral</h3>')
    html.append('<p>Old frames never retire. Every lesson includes activities that recycle previous frames alongside new ones. If the student only practises new material, old material decays. The cocktail drills, frame sprints, and interleaving activities exist to prevent this. If a frame from Stage 1 is still slow in Stage 3, it needs more airtime, not more explanation.</p>')

    html.append('<h3>Prosody is identity</h3>')
    html.append('<p>The three French sounds (nasal vowels, uvular R, final-syllable stress) are established in Lesson 1 and reinforced throughout. If the student\'s prosody drifts back to English patterns, fix it immediately. A student with perfect vocabulary and English prosody will be answered in English. A student with limited vocabulary and French prosody will be answered in French. Prosody determines whether the listener treats them as a French speaker or a tourist.</p>')

    html.append('<h3>The teacher\'s silence is productive</h3>')
    html.append('<p>The most common mistake new teachers make is filling silence. When the student pauses to think, wait. Count to three silently. The pause is where learning happens: the student is searching their memory for the right frame. If you fill the silence for them, you rob them of the retrieval practice. Only prompt if they are genuinely stuck (not just slow), and when you do prompt, give the first syllable, not the whole word.</p>')

    html.append('<h3>Celebrate distance, not perfection</h3>')
    html.append('<p>At the end of every lesson, the student should feel they can do something they could not do an hour ago. This is more important than covering every planned activity. If you run out of time because the student needed extra practice on a difficult frame, that is a good lesson, not a failed one. The manual gives you more material than you need for each lesson so you can adapt to the student\'s pace.</p>')

    return "\n".join(html)


# ---------------------------------------------------------------------------
# 6. BOOK ASSEMBLY
# ---------------------------------------------------------------------------

def build_epub(data):
    book = epub.EpubBook()

    book.set_identifier("fluentish-teaching-manual-v1")
    book.set_title("FluentISH: The Complete Teaching Manual")
    book.set_language("en")
    book.add_author("FluentISH")

    # Stylesheet
    css = epub.EpubItem(
        uid="style",
        file_name="style/book.css",
        media_type="text/css",
        content=BOOK_CSS.encode("utf-8"),
    )
    book.add_item(css)

    chapters = []
    spine_items = ["nav"]
    toc = []

    # ---- TITLE PAGE ----
    title_html = """
    <div class="title-page">
        <h1>FluentISH</h1>
        <p class="subtitle">The Complete Teaching Manual</p>
        <p class="edition">24 Lessons &middot; 30 Frames &middot; Zero to FluentISH</p>
        <p class="edition">Teacher's Edition for 1-to-1 Instruction</p>
        <hr style="margin-top:3em; width:40%; margin-left:auto; margin-right:auto;">
        <p style="margin-top:1em; font-size:0.85em; color:#6B7280;">A lesson-by-lesson guide to teaching spoken French<br/>using the frame-and-filler method.</p>
    </div>
    """
    ch_title = epub.EpubHtml(title="Title", file_name="title.xhtml")
    ch_title.content = f'<html><head><link rel="stylesheet" href="style/book.css"/></head><body>{title_html}</body></html>'
    ch_title.add_item(css)
    book.add_item(ch_title)
    chapters.append(ch_title)
    spine_items.append(ch_title)

    # ---- INTRODUCTION ----
    intro_html = """
    <h1>How to Use This Manual</h1>

    <h3>What This Is</h3>
    <p>This is a complete, lesson-by-lesson teaching manual for the FluentISH method. It is designed for a teacher who speaks French fluently and wants a structured system for teaching spoken French to adult learners in 1-to-1 sessions.</p>
    <p>Each lesson is fully scripted: it tells you what to teach, how to teach it, what to say, what to listen for, what to do when the student struggles, and how to close the lesson. You do not need to prepare anything beyond reading the lesson before the session.</p>

    <h3>The Method: Frames and Fillers</h3>
    <p>The FluentISH method is built on a single idea from usage-based linguistics: fluent speakers do not assemble sentences word by word. They retrieve pre-built chunks and fill in the variable parts. A frame like "je suis ___" is a chunk. The blank is a slot. The student learns the chunk, then learns to fill the slot with words from their own life.</p>
    <p>Over 24 lessons, the student accumulates 30 frames. These 30 frames, combined with the student's own vocabulary, generate hundreds of sentences. The frames are ordered by frequency in real spoken French, so the student learns the most useful patterns first.</p>

    <h3>The Five Stages</h3>
    <p><strong>Stage 1: The Ignition (Lessons 1-3).</strong> Four frames. The student can introduce themselves and order in a cafe. Your role: heavy modelling, maximum safety. You produce 70% of the French.</p>
    <p><strong>Stage 2: The Toolkit (Lessons 4-7).</strong> Ten frames. The student can handle basic transactions and recover when lost. Your role: 50/50 production. Introduce elicitation alongside recasting.</p>
    <p><strong>Stage 3: The Weave (Lessons 8-12).</strong> Eighteen frames. The student can link ideas, tell stories, and sustain 5+ minutes of conversation. Your role: the student produces 70%. Prioritise fluency over accuracy.</p>
    <p><strong>Stage 4: The Ring (Lessons 13-18).</strong> Twenty-four frames. The student can debate, disagree, and handle unexpected situations for 10+ minutes. Your role: conversation partner, not instructor. Minimal correction.</p>
    <p><strong>Stage 5: The Road (Lessons 19-24).</strong> Thirty frames. The student navigates a full day in French, makes phone calls, resolves problems. Your role: scene-setter. No correction during simulations.</p>

    <h3>Correction Strategy Progression</h3>
    <p>Your correction approach evolves across the five stages:</p>
    <div class="teacher-box">
        <p><strong>Stage 1:</strong> Recasts only. The student says it wrong; you say it right. No explicit correction. No "try again".</p>
        <p><strong>Stage 2:</strong> Recasts plus occasional elicitation. If the student hesitates, give the first syllable, not the whole word.</p>
        <p><strong>Stage 3:</strong> Elicitation is primary. Pause, raise an eyebrow, let them self-correct. Only recast if they cannot find it in 3 seconds. Delayed correction: note errors and address the top 2 after the activity.</p>
        <p><strong>Stage 4:</strong> Minimal correction. Do not interrupt flow. Address fossilised errors in debrief only.</p>
        <p><strong>Stage 5:</strong> No correction during simulations. You are a French speaker, not a teacher. Debrief vocabulary gaps afterwards.</p>
    </div>

    <h3>Phonetic Guide</h3>
    <p>This manual uses informal English approximations for pronunciation (e.g., "zhuh SWEE" for <em>je suis</em>). CAPS indicate the stressed syllable. These are not IPA transcriptions. As a French speaker, you should model the correct pronunciation live. The phonetic guides are here so you can see at a glance what the student is aiming for and where English speakers typically go wrong.</p>

    <h3>Lesson Structure</h3>
    <p>Every lesson follows the same structure:</p>
    <ol>
        <li><strong>Warm-up</strong> (3 min): Frame sprint reviewing previous material</li>
        <li><strong>New material</strong> (10-15 min): Introduce new frames, model, drill</li>
        <li><strong>Practice</strong> (15-20 min): Activities that combine new and old frames</li>
        <li><strong>Free production</strong> (10-15 min): The student uses everything in context</li>
        <li><strong>Close</strong> (5 min): Confidence builder, checkpoint, homework</li>
    </ol>
    <p>Total lesson time: approximately 50-60 minutes. Adjust to your student's energy and focus.</p>
    """
    ch_intro = epub.EpubHtml(title="How to Use This Manual", file_name="intro.xhtml")
    ch_intro.content = f'<html><head><link rel="stylesheet" href="style/book.css"/></head><body>{intro_html}</body></html>'
    ch_intro.add_item(css)
    book.add_item(ch_intro)
    chapters.append(ch_intro)
    spine_items.append(ch_intro)
    toc.append(ch_intro)

    # ---- COURSE OVERVIEW ----
    overview_html = generate_course_overview(data)
    ch_overview = epub.EpubHtml(title="Course Overview", file_name="overview.xhtml")
    ch_overview.content = f'<html><head><link rel="stylesheet" href="style/book.css"/></head><body>{overview_html}</body></html>'
    ch_overview.add_item(css)
    book.add_item(ch_overview)
    chapters.append(ch_overview)
    spine_items.append(ch_overview)
    toc.append(ch_overview)

    # ---- STAGE CHAPTERS ----
    stages = data["stages"]
    lessons = data["lessons"]
    bbs = data.get("buildingBlockStages", [])

    for stage in stages:
        stage_num = stage["num"]
        stage_lessons = [l for l in lessons if l["stage"] == stage_num]

        stage_content = generate_stage_intro(stage)

        lesson_sub_chapters = []

        for lesson in stage_lessons:
            lesson_content = generate_lesson_chapter(lesson, stage, bbs, lessons)

            lesson_fname = f"lesson_{lesson['num']:02d}.xhtml"
            ch_lesson = epub.EpubHtml(
                title=f"Lesson {lesson['num']}: {lesson['title']}",
                file_name=lesson_fname,
            )
            ch_lesson.content = f'<html><head><link rel="stylesheet" href="style/book.css"/></head><body>{lesson_content}</body></html>'
            ch_lesson.add_item(css)
            book.add_item(ch_lesson)
            chapters.append(ch_lesson)
            spine_items.append(ch_lesson)
            lesson_sub_chapters.append(ch_lesson)

        # Stage transition (except stage 5)
        if stage_num < 5:
            transition_html = generate_stage_transition(stage)
            last_lesson_ch = lesson_sub_chapters[-1]
            # Append transition to the last lesson of the stage
            existing = last_lesson_ch.content
            insert_point = existing.rfind("</body>")
            last_lesson_ch.content = existing[:insert_point] + f"\n<hr/>\n{transition_html}\n" + existing[insert_point:]

        # Stage overview page
        stage_fname = f"stage_{stage_num}.xhtml"
        ch_stage = epub.EpubHtml(
            title=f"Stage {stage_num}: {stage['name']}",
            file_name=stage_fname,
        )
        ch_stage.content = f'<html><head><link rel="stylesheet" href="style/book.css"/></head><body>{stage_content}</body></html>'
        ch_stage.add_item(css)
        book.add_item(ch_stage)
        chapters.append(ch_stage)
        spine_items.insert(spine_items.index(lesson_sub_chapters[0]), ch_stage)

        # TOC: stage with lesson sub-items
        stage_toc = epub.Section(f"Stage {stage_num}: {stage['name']}")
        toc.append((stage_toc, [ch_stage] + lesson_sub_chapters))

    # Build TOC and spine
    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    epub.write_epub(EPUB_PATH, book, {})

    file_size = os.path.getsize(EPUB_PATH)
    print(f"EPUB generated: {EPUB_PATH}")
    print(f"File size: {file_size / 1024:.1f} KB")
    return EPUB_PATH


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Extracting data from blueprint.html...")
    data = extract_data()
    print(f"Found {len(data['stages'])} stages, {len(data['lessons'])} lessons")

    print("Generating EPUB...")
    path = build_epub(data)
    print(f"Done! Manual saved to: {path}")
