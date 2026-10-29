from flask import Flask, render_template, request, jsonify
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import SessionLocal
from models import Novel, DailyAnswer
from compare import (
    compare_guess,
    _normalize_rating_5,
    _round_to_half,
    _text_key
)

from novel_metadata import snapshot_data

app = Flask(__name__)

def game_data(novel):
    from novel_metadata import game_data as build_game_data
    return build_game_data(novel)


def get_novels():
    with SessionLocal() as session:
        novels = session.scalars(
            select(Novel).order_by(Novel.id)
        ).all()

        return [game_data(novel) for novel in novels]


def get_daily_answer():
    today = datetime.now(UTC).date()

    with SessionLocal.begin() as session:

        saved_answer = session.get(DailyAnswer, today)

        if saved_answer is not None:
            return snapshot_data(saved_answer.answer_data)

        # retrieve stable database IDs in a defined order
        novel_ids = session.scalars(
            select(Novel.id)
            .where(Novel.daily_eligible.is_(True))
            .order_by(Novel.id)
        ).all()

        if not novel_ids:
            return None

        index = today.toordinal() % len(novel_ids)
        selected_id = novel_ids[index]

        selected_novel = session.get(Novel, selected_id)

        # save the novel's data for this specific day
        statement = pg_insert(DailyAnswer).values(
            day=today,
            novel_id=selected_id,
            answer_data=game_data(selected_novel),
        )

        # prevent duplicate entries if two requests arrive simultaneously
        statement = statement.on_conflict_do_nothing(
            index_elements=[DailyAnswer.day]
        )

        session.execute(statement)

        saved_answer = session.get(DailyAnswer, today)

        return snapshot_data(saved_answer.answer_data)

@app.route("/")
def index():
    novels = get_novels()

    return render_template(
        "index.html",
        novels=[novel["title"] for novel in novels]
    )

@app.route("/guess", methods=["POST"])
def guess():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request"}), 400

    guess_title = data.get("title")

    if not isinstance(guess_title, str):
        return jsonify({"error": "Invalid title"}), 400

    novels = get_novels()

    guess_novel = next(
        (
            novel for novel in novels
            if _text_key(novel["title"]) == _text_key(guess_title)
        ),
        None
    )

    if not guess_novel:
        return jsonify({"error": "Novel not found"}), 400

    answer = get_daily_answer()

    if not answer:
        return jsonify({
            "error": "No novels available"
        }), 503

    feedback = compare_guess(guess_novel, answer)

    return jsonify(feedback)

@app.route("/answer")
def get_answer():

    answer = get_daily_answer()

    if not answer:
        return jsonify({
            "error": "No novels available"
        }), 503

    # normalize rating to 0-5 for the UI
    r_raw = _normalize_rating_5(
        answer.get("rating")
    )

    r5 = None

    if r_raw is not None:
        r5 = max(
            0.0,
            min(5.0, _round_to_half(r_raw))
        )

    return jsonify({
        "title": answer["title"],
        "author": answer["author"],
        "genres": answer["genres"],
        "rating": answer["rating"],
        "rating5": r5,
        "chapters": answer.get("chapters"),
        "original_chapters_total": answer.get("original_chapters_total"),
        "original_chapters_main": answer.get("original_chapters_main"),
        "original_chapters_extra": answer.get("original_chapters_extra"),
        "publication_status": answer.get("publication_status", "unknown"),
        "main_publication_status": answer.get("main_publication_status", "unknown")
    })


if __name__ == "__main__":
    app.run(debug=True)
