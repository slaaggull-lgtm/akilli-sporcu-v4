import os
import random
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, flash, make_response
)
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "akilli_sporcu_secret")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///akillitakip.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# =====================================================
# VERİTABANI MODELLERİ
# =====================================================

class Athlete(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, default=25)
    height = db.Column(db.Integer, default=175)
    weight = db.Column(db.Float, default=70)
    sport_branch = db.Column(db.String(50), default="Koşu")

    trainings = db.relationship("Training", backref="athlete", lazy=True, cascade="all, delete-orphan")
    goals = db.relationship("Goal", backref="athlete", lazy=True, cascade="all, delete-orphan")
    achievements = db.relationship("Achievement", backref="athlete", lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="athlete", lazy=True, cascade="all, delete-orphan")
    ai_reports = db.relationship("AIReport", backref="athlete", lazy=True, cascade="all, delete-orphan")


class Training(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athlete.id"), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    bpm = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    calories = db.Column(db.Integer, nullable=False)
    fatigue = db.Column(db.Integer, default=5)
    notes = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)


class Goal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athlete.id"), nullable=False)
    type = db.Column(db.String(50))
    period = db.Column(db.String(50))
    target_value = db.Column(db.Integer)
    current_value = db.Column(db.Integer, default=0)


class Achievement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athlete.id"), nullable=False)
    title = db.Column(db.String(100))
    description = db.Column(db.String(255))
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athlete.id"), nullable=False)
    message = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AIReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athlete.id"), nullable=False)
    risk_score = db.Column(db.Integer)
    risk_level = db.Column(db.String(20))
    feedback = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# =====================================================
# SAĞLIK METRİKLERİ
# =====================================================

def calculate_health_metrics(athlete):
    bmi = round(athlete.weight / ((athlete.height / 100) ** 2), 1) if athlete.height > 0 else 0
    max_bpm = 220 - athlete.age
    target_min = int(max_bpm * 0.60)
    target_max = int(max_bpm * 0.85)
    bmr = (10 * athlete.weight + 6.25 * athlete.height - 5 * athlete.age + 5)

    if bmi < 18.5:
        bmi_status, bmi_color = "Düşük Kilolu", "amber"
    elif bmi < 25:
        bmi_status, bmi_color = "Normal", "emerald"
    elif bmi < 30:
        bmi_status, bmi_color = "Fazla Kilolu", "amber"
    else:
        bmi_status, bmi_color = "Obez", "rose"

    return {
        "bmi": bmi,
        "bmi_status": bmi_status,
        "bmi_color": bmi_color,
        "max_bpm": max_bpm,
        "target_min": target_min,
        "target_max": target_max,
        "target_range": f"{target_min}-{target_max} bpm",
        "daily_calories": int(bmr * 1.375),
    }


# =====================================================
# AI RİSK MOTORU (kural tabanlı yapay zeka koçu)
# =====================================================

def run_ai_and_risk_engine(athlete_id):
    athlete = db.session.get(Athlete, athlete_id)
    trainings = (Training.query.filter_by(athlete_id=athlete_id)
                 .order_by(Training.date.desc()).limit(5).all())

    if not trainings:
        return 0, "Düşük", "Henüz yeterli veri bulunmuyor. İlk antrenmanını ekleyerek analizi başlat."

    avg_bpm = sum(t.bpm for t in trainings) / len(trainings)
    avg_fatigue = sum((t.fatigue or 5) for t in trainings) / len(trainings)
    avg_duration = sum(t.duration for t in trainings) / len(trainings)

    risk_score = 10
    reasons = []

    if avg_bpm > 160:
        risk_score += 40
        reasons.append("ortalama nabız çok yüksek")
    elif avg_bpm > 145:
        risk_score += 25
        reasons.append("ortalama nabız yüksek seyrediyor")

    if athlete and avg_bpm > (athlete.age + 120):
        risk_score += 20
        reasons.append("yaşa göre nabız sınırı aşılıyor")

    high_bpm_count = len([t for t in trainings if t.bpm > 155])
    if high_bpm_count >= 3:
        risk_score += 20
        reasons.append("art arda yüksek tempolu seanslar")

    if avg_fatigue >= 8:
        risk_score += 15
        reasons.append("algılanan yorgunluk seviyesi kritik")

    if avg_duration > 90:
        risk_score += 10
        reasons.append("seans süreleri uzun")

    risk_score = min(risk_score, 100)

    if risk_score >= 70:
        risk_level = "Yüksek"
        feedback = ("Aşırı yüklenme riski tespit edildi (" + ", ".join(reasons) + "). "
                    "1-2 gün aktif dinlenme ve düşük tempolu toparlanma antrenmanı önerilir.")
    elif risk_score >= 40:
        risk_level = "Orta"
        feedback = ("Antrenman yoğunluğu yükseliyor (" + (", ".join(reasons) if reasons else "tempo artışı") + "). "
                    "Yoğunluğu kademeli artırın ve uyku/beslenmeyi takip edin.")
    else:
        risk_level = "Düşük"
        feedback = "Performans değerleri normal aralıkta. Mevcut programa güvenle devam edebilirsiniz."

    report = AIReport(athlete_id=athlete_id, risk_score=risk_score,
                       risk_level=risk_level, feedback=feedback)
    db.session.add(report)
    db.session.commit()

    return risk_score, risk_level, feedback


# =====================================================
# BAŞARI SİSTEMİ
# =====================================================

def unlock_achievement(athlete_id, title, description):
    exists = Achievement.query.filter_by(athlete_id=athlete_id, title=title).first()
    if not exists:
        ach = Achievement(athlete_id=athlete_id, title=title, description=description)
        db.session.add(ach)
        notification = Notification(athlete_id=athlete_id, message=f"🏆 Yeni başarı: {title}")
        db.session.add(notification)
        db.session.commit()


def check_achievements(athlete_id):
    trainings = Training.query.filter_by(athlete_id=athlete_id).all()
    count = len(trainings)
    total_calories = sum(t.calories for t in trainings)
    total_duration = sum(t.duration for t in trainings)

    if count >= 1:
        unlock_achievement(athlete_id, "İlk Adım", "İlk antrenman tamamlandı.")
    if count >= 5:
        unlock_achievement(athlete_id, "İstikrarlı Sporcu", "5 antrenman tamamlandı.")
    if count >= 10:
        unlock_achievement(athlete_id, "Disiplin Ustası", "10 antrenman tamamlandı.")
    if count >= 25:
        unlock_achievement(athlete_id, "Demir Disiplin", "25 antrenman tamamlandı.")
    if total_calories >= 5000:
        unlock_achievement(athlete_id, "Kalori Avcısı", "5000 kalori yakıldı.")
    if total_calories >= 15000:
        unlock_achievement(athlete_id, "Yanan Motor", "15000 kalori yakıldı.")
    if total_duration >= 1000:
        unlock_achievement(athlete_id, "Dayanıklılık Uzmanı", "1000 dakika antrenman.")


# =====================================================
# PERFORMANS SKORU
# =====================================================

def calculate_performance_score(athlete_id):
    trainings = Training.query.filter_by(athlete_id=athlete_id).all()
    if not trainings:
        return 0
    avg_bpm = sum(t.bpm for t in trainings) / len(trainings)
    avg_duration = sum(t.duration for t in trainings) / len(trainings)
    score = (avg_duration * 0.7 + avg_bpm * 0.3)
    return min(int(score), 100)


def get_context_data(current_athlete):
    """Tüm sayfalarda ortak kullanılan veri seti (sidebar, bildirimler, sporcu listesi vb.)"""
    athletes = Athlete.query.order_by(Athlete.id).all()

    trainings = (Training.query.filter_by(athlete_id=current_athlete.id)
                 .order_by(Training.date.desc()).all())

    total_trainings = len(trainings)
    avg_bpm = int(sum(t.bpm for t in trainings) / total_trainings) if total_trainings else 0
    total_duration = sum(t.duration for t in trainings)
    total_calories = sum(t.calories for t in trainings)
    best_bpm = max([t.bpm for t in trainings], default=0)
    longest_training = max([t.duration for t in trainings], default=0)
    weekly_count = len([t for t in trainings if t.date >= (datetime.utcnow() - timedelta(days=7))])

    health = calculate_health_metrics(current_athlete)
    performance_score = calculate_performance_score(current_athlete.id)

    last_report = (AIReport.query.filter_by(athlete_id=current_athlete.id)
                   .order_by(AIReport.created_at.desc()).first())

    risk_score = last_report.risk_score if last_report else 0
    risk_level = last_report.risk_level if last_report else "Düşük"
    ai_feedback = last_report.feedback if last_report else "Analiz bekleniyor. İlk antrenmanını ekle."

    risk_history = (AIReport.query.filter_by(athlete_id=current_athlete.id)
                    .order_by(AIReport.created_at.asc()).all())

    goals = Goal.query.filter_by(athlete_id=current_athlete.id).all()
    if not goals:
        g1 = Goal(athlete_id=current_athlete.id, type="Süre", period="Haftalık",
                  target_value=180, current_value=min(total_duration, 180))
        g2 = Goal(athlete_id=current_athlete.id, type="Antrenman", period="Aylık",
                  target_value=12, current_value=min(total_trainings, 12))
        g3 = Goal(athlete_id=current_athlete.id, type="Kalori", period="Haftalık",
                  target_value=2000, current_value=min(total_calories, 2000))
        db.session.add_all([g1, g2, g3])
        db.session.commit()
        goals = [g1, g2, g3]

    notifications = (Notification.query.filter_by(athlete_id=current_athlete.id)
                     .order_by(Notification.created_at.desc()).limit(20).all())
    unread_notif_count = len([n for n in notifications if not n.is_read])

    achievements = Achievement.query.filter_by(athlete_id=current_athlete.id).order_by(Achievement.unlocked_at.desc()).all()
    all_possible_achievements = 7

    today = datetime.utcnow().date()
    calendar_days = []
    for i in range(34, -1, -1):
        day = today - timedelta(days=i)
        day_trainings = [t for t in trainings if t.date.date() == day]
        count = len(day_trainings)
        calendar_days.append({
            "date_str": day.strftime("%d %b"),
            "weekday": day.strftime("%a"),
            "count": count,
            "full_date": day.strftime("%d.%m.%Y"),
        })

    return dict(
        athletes=athletes,
        current_athlete=current_athlete,
        trainings=trainings,
        total_trainings=total_trainings,
        avg_bpm=avg_bpm,
        total_duration=total_duration,
        total_calories=total_calories,
        best_bpm=best_bpm,
        longest_training=longest_training,
        weekly_count=weekly_count,
        performance_score=performance_score,
        risk_score=risk_score,
        risk_level=risk_level,
        ai_feedback=ai_feedback,
        risk_history=risk_history,
        health=health,
        goals=goals,
        notifications=notifications,
        unread_notif_count=unread_notif_count,
        achievements=achievements,
        all_possible_achievements=all_possible_achievements,
        calendar_days=calendar_days,
    )


def get_current_athlete():
    athletes = Athlete.query.order_by(Athlete.id).all()
    if not athletes:
        demo = Athlete(name="Demo Sporcu", age=25, height=175, weight=70, sport_branch="Koşu")
        db.session.add(demo)
        db.session.commit()
        athletes = [demo]

    current_athlete_id = request.args.get("athlete_id", athletes[0].id, type=int)
    current_athlete = db.session.get(Athlete, current_athlete_id)
    if not current_athlete:
        current_athlete = athletes[0]
    return current_athlete


# =====================================================
# SAYFALAR
# =====================================================

@app.route("/")
def index():
    current_athlete = get_current_athlete()
    ctx = get_context_data(current_athlete)
    return render_template("index.html", active_page="dashboard", **ctx)


@app.route("/analiz")
def analytics():
    current_athlete = get_current_athlete()
    ctx = get_context_data(current_athlete)
    return render_template("analytics.html", active_page="analiz", **ctx)


@app.route("/ai-koc")
def ai_coach():
    current_athlete = get_current_athlete()
    ctx = get_context_data(current_athlete)
    return render_template("ai_coach.html", active_page="ai", **ctx)


@app.route("/takvim")
def calendar_view():
    current_athlete = get_current_athlete()
    ctx = get_context_data(current_athlete)
    return render_template("calendar.html", active_page="takvim", **ctx)


@app.route("/profil")
def profile():
    current_athlete = get_current_athlete()
    ctx = get_context_data(current_athlete)
    return render_template("profile.html", active_page="profil", **ctx)


# =====================================================
# ANTRENMAN EKLE
# =====================================================

@app.route("/training/add", methods=["POST"])
def add_training():
    try:
        athlete_id = int(request.form.get("athlete_id"))
        t_type = request.form.get("type")
        bpm = int(request.form.get("bpm"))
        duration = int(request.form.get("duration"))
        fatigue = int(request.form.get("fatigue", 5))
        notes = request.form.get("notes", "")
    except (TypeError, ValueError):
        flash("Geçersiz veri girdiniz, lütfen kontrol edin.", "error")
        return redirect(url_for("index"))

    calories = int(duration * 8 * (bpm / 130))

    training = Training(
        athlete_id=athlete_id, type=t_type, bpm=bpm, duration=duration,
        calories=calories, fatigue=fatigue, notes=notes
    )
    db.session.add(training)

    notification = Notification(athlete_id=athlete_id, message=f"✅ {t_type} antrenmanı eklendi ({duration} dk).")
    db.session.add(notification)
    db.session.commit()

    run_ai_and_risk_engine(athlete_id)
    check_achievements(athlete_id)

    # Hedefleri güncelle
    goals = Goal.query.filter_by(athlete_id=athlete_id).all()
    for g in goals:
        if g.type == "Süre":
            g.current_value = min(g.current_value + duration, g.target_value)
        elif g.type == "Antrenman":
            g.current_value = min(g.current_value + 1, g.target_value)
        elif g.type == "Kalori":
            g.current_value = min(g.current_value + calories, g.target_value)
    db.session.commit()

    flash("Antrenman başarıyla kaydedildi ve analiz edildi.", "success")
    return redirect(url_for("index", athlete_id=athlete_id))


# =====================================================
# GRAFİK VERİLERİ (sınırlandırılmış zaman aralığı destekli)
# =====================================================

@app.route("/chart-data/<int:athlete_id>")
def chart_data(athlete_id):
    days_param = request.args.get("days", "all")

    query = Training.query.filter_by(athlete_id=athlete_id).order_by(Training.date.asc())

    if days_param != "all":
        try:
            days = int(days_param)
            since = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Training.date >= since)
        except ValueError:
            pass

    data = query.all()

    risk_data = []
    for t in data:
        if t.bpm > 160:
            risk_data.append(80)
        elif t.bpm > 145:
            risk_data.append(50)
        else:
            risk_data.append(20)

    type_counts = {}
    for t in data:
        type_counts[t.type] = type_counts.get(t.type, 0) + 1

    return jsonify({
        "labels": [t.date.strftime("%d/%m %H:%M") for t in data],
        "bpm": [t.bpm for t in data],
        "duration": [t.duration for t in data],
        "calories": [t.calories for t in data],
        "fatigue": [(t.fatigue or 5) for t in data],
        "risk": risk_data,
        "type_labels": list(type_counts.keys()),
        "type_counts": list(type_counts.values()),
    })


# =====================================================
# SPORCU EKLE / GÜNCELLE / SİL
# =====================================================

@app.route("/athlete/add", methods=["POST"])
def add_athlete():
    name = request.form.get("name")
    if name:
        athlete = Athlete(name=name, age=25, height=175, weight=70, sport_branch="Koşu")
        db.session.add(athlete)
        db.session.commit()
        flash(f"{name} sisteme eklendi.", "success")
        return redirect(url_for("index", athlete_id=athlete.id))
    return redirect(url_for("index"))


@app.route("/athlete/update/<int:id>", methods=["POST"])
def update_athlete(id):
    athlete = db.session.get(Athlete, id)
    if athlete:
        athlete.name = request.form.get("name", athlete.name)
        athlete.age = int(request.form.get("age", athlete.age) or athlete.age)
        athlete.height = int(request.form.get("height", athlete.height) or athlete.height)
        athlete.weight = float(request.form.get("weight", athlete.weight) or athlete.weight)
        athlete.sport_branch = request.form.get("sport_branch", athlete.sport_branch)
        db.session.commit()
        flash("Profil güncellendi.", "success")
    return redirect(url_for("profile", athlete_id=id))


@app.route("/athlete/delete/<int:id>")
def delete_athlete(id):
    athlete = db.session.get(Athlete, id)
    if athlete:
        db.session.delete(athlete)
        db.session.commit()
        flash("Sporcu silindi.", "success")
    return redirect(url_for("index"))


# =====================================================
# ANTRENMAN SİL
# =====================================================

@app.route("/training/delete/<int:id>")
def delete_training(id):
    tr = db.session.get(Training, id)
    if not tr:
        return redirect(url_for("index"))
    athlete_id = tr.athlete_id
    db.session.delete(tr)
    db.session.commit()
    flash("Antrenman silindi.", "success")
    return redirect(url_for("index", athlete_id=athlete_id))


# =====================================================
# SİMÜLASYON (Rastgele Sensör Verisi)
# =====================================================

@app.route("/training/simulate/<int:athlete_id>")
def simulate_training(athlete_id):
    types = ["Koşu", "Bisiklet", "Fitness", "Yüzme", "Futbol"]
    t_type = random.choice(types)
    bpm = random.randint(95, 175)
    duration = random.randint(20, 100)
    fatigue = random.randint(3, 9)
    calories = int(duration * 8 * (bpm / 130))

    training = Training(athlete_id=athlete_id, type=t_type, bpm=bpm, duration=duration,
                         calories=calories, fatigue=fatigue, notes="Simüle edilmiş sensör verisi.")
    db.session.add(training)
    db.session.add(Notification(athlete_id=athlete_id, message=f"📡 Sensör verisi simüle edildi: {t_type}"))
    db.session.commit()

    run_ai_and_risk_engine(athlete_id)
    check_achievements(athlete_id)

    return redirect(url_for("index", athlete_id=athlete_id))


# =====================================================
# PDF RAPOR
# =====================================================

@app.route("/export-pdf/<int:athlete_id>")
def export_pdf(athlete_id):
    athlete = db.session.get(Athlete, athlete_id)
    trainings = Training.query.filter_by(athlete_id=athlete_id).order_by(Training.date.desc()).all()
    report = (AIReport.query.filter_by(athlete_id=athlete_id)
              .order_by(AIReport.created_at.desc()).first())
    health = calculate_health_metrics(athlete) if athlete else {}
    achievements = Achievement.query.filter_by(athlete_id=athlete_id).all()

    return render_template(
        "pdf_template.html",
        athlete=athlete, trainings=trainings, report=report,
        health=health, achievements=achievements,
        generated_at=datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    )


# =====================================================
# API İSTATİSTİK
# =====================================================

@app.route("/api/stats/<int:id>")
def api_stats(id):
    athlete = db.session.get(Athlete, id)
    if not athlete:
        return jsonify({"error": "sporcu bulunamadı"})
    trainings = Training.query.filter_by(athlete_id=id).all()
    return jsonify({
        "name": athlete.name,
        "training_count": len(trainings),
        "total_calories": sum(t.calories for t in trainings),
        "average_bpm": int(sum(t.bpm for t in trainings) / len(trainings)) if trainings else 0,
    })


# =====================================================
# BİLDİRİMLER
# =====================================================

@app.route("/notifications/read/<int:id>")
def read_notification(id):
    notif = db.session.get(Notification, id)
    if notif:
        notif.is_read = True
        db.session.commit()
        return redirect(url_for("index", athlete_id=notif.athlete_id))
    return redirect(url_for("index"))


@app.route("/notifications/read_all/<int:athlete_id>")
def read_all_notifications(athlete_id):
    Notification.query.filter_by(athlete_id=athlete_id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"status": "ok"})


# =====================================================
# UYGULAMA BAŞLAT
# =====================================================

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
