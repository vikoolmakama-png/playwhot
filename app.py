from flask import Flask, render_template, request, redirect, session, flash, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import secrets
import time
from game_engine import STAKES, start_game, player_play

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg:///" + "playwhot"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    balance = db.Column(db.Integer, default=70)
    game_balance = db.Column(db.Integer, nullable=False, default=70)
    referral_code = db.Column(db.String(20), unique=True)
    referred_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Deposit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    sender_name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default="pending")
    referral_rewarded = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Withdrawal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    amount = db.Column(db.Integer, nullable=False)
    bank_name = db.Column(db.String(100))
    account_name = db.Column(db.String(120))
    account_number = db.Column(db.String(30))
    status = db.Column(db.String(30), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class GameHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    result = db.Column(db.String(30))
    amount = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@app.route("/")
def home():
    return render_template("welcome.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        entered_code = (request.form.get("referral_code") or request.args.get("ref", "")).strip().upper()

        if not fullname or not username or not email or len(password) < 8:
            flash("Enter valid details and a password of at least 8 characters.")
            return redirect("/register")

        if User.query.filter(
            (User.username == username) | (User.email == email)
        ).first():
            flash("Username or email already exists.")
            return redirect("/register")

        referrer = None

        if entered_code:
            referrer = User.query.filter_by(
                referral_code=entered_code
            ).first()

            if not referrer:
                flash("Invalid referral code.")
                return redirect("/register")

        user = User(
            fullname=fullname,
            username=username,
            email=email,
            password=generate_password_hash(password),
            balance=70,
            referral_code=secrets.token_hex(4).upper(),
            referred_by_id=referrer.id if referrer else None
        )

        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        return redirect("/dashboard")

    return render_template("register.html", referral_code=request.args.get("ref", "").strip().upper())


@app.route("/referrals")
def referrals():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])

    invited = User.query.filter_by(referred_by_id=user.id).all()
    referral_link = request.host_url.rstrip("/") + "/register?ref=" + user.referral_code

    return render_template(
        "referrals.html",
        user=user,
        invited=invited,
        referral_link=referral_link
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            return redirect("/dashboard")

        flash("Incorrect username or password.")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect("/login")

    return render_template("dashboard.html", user=user)


@app.route("/deposit", methods=["GET", "POST"])
def deposit():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":
        sender = request.form.get("sender_name", "").strip()

        try:
            amount = int(request.form.get("amount", 0))
        except ValueError:
            amount = 0

        if not sender or amount < 200:
            flash("Minimum deposit is ₦200. Enter a valid sender name and amount.")
            return redirect("/deposit")

        payment = Deposit(
            user_id=session["user_id"],
            sender_name=sender,
            amount=amount
        )

        db.session.add(payment)
        db.session.commit()

        flash("Deposit submitted for admin verification.")
        return redirect("/dashboard")

    return render_template("deposit.html")


def reward_referrer_for_deposit(payment):
    """Call only after an administrator verifies a deposit."""

    if payment.status != "approved" or payment.referral_rewarded:
        return 0

    depositor = db.session.get(User, payment.user_id)

    if not depositor or not depositor.referred_by_id:
        return 0

    approved_count = Deposit.query.filter_by(
        user_id=depositor.id,
        status="approved"
    ).count()

    if approved_count > 5:
        return 0

    referrer = db.session.get(User, depositor.referred_by_id)

    if not referrer:
        return 0

    commission = int(payment.amount * 0.35)

    referrer.balance += commission
    payment.referral_rewarded = True

    return commission




@app.route("/withdraw", methods=["GET", "POST"])
def withdraw():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect("/login")

    available_balance = user.balance or 0

    if request.method == "POST":
        account_number = request.form.get("account_number", "").strip()
        account_name = request.form.get("account_name", "").strip()
        bank_name = request.form.get("bank_name", "").strip()

        try:
            amount = int(request.form.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0

        if not all([account_number, account_name, bank_name]):
            flash("Please complete all bank details.")
            return redirect("/withdraw")

        if not account_number.isdigit() or not (10 <= len(account_number) <= 20):
            flash("Enter a valid account number.")
            return redirect("/withdraw")

        if amount < 300:
            flash("Minimum withdrawal is ₦300.")
            return redirect("/withdraw")

        if amount > available_balance:
            flash("Insufficient available balance.")
            return redirect("/withdraw")

        withdrawal = Withdrawal(
            user_id=user.id,
            amount=amount,
            bank_name=bank_name,
            account_name=account_name,
            account_number=account_number,
            status="pending"
        )

        user.balance -= amount
        db.session.add(withdrawal)
        db.session.commit()

        flash("Withdrawal submitted. ₦" + str(amount) + " deducted from your balance immediately.")
        return redirect("/dashboard")

    return render_template(
        "withdraw.html",
        user=user,
        available_balance=available_balance
    )



@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect("/login")

    deposits = Deposit.query.filter_by(
        user_id=user.id
    ).order_by(Deposit.created_at.desc()).all()

    withdrawals = Withdrawal.query.filter_by(
        user_id=user.id
    ).order_by(Withdrawal.created_at.desc()).all()

    return render_template(
        "history.html",
        user=user,
        deposits=deposits,
        withdrawals=withdrawals
    )





def game_ajax_response():
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        user = db.session.get(User, session.get("user_id"))
        html = render_template(
            "game.html",
            stakes=STAKES,
            credits=user.balance if user else 0,
            game=session.get("whot_game")
        )
        return jsonify({"html": html, "ai_pending": bool((session.get("whot_game") or {}).get("ai_pending"))})
    return redirect("/game")


@app.route("/game")
def game():
    if "user_id" not in session:
        return redirect("/login")
    user = db.session.get(User, session["user_id"])
    if not user:
        session.clear()
        return redirect("/login")
    return render_template("game.html", stakes=STAKES,
                           credits=user.balance,
                           game=session.get("whot_game"))


@app.route("/game/start", methods=["POST"])
def start_whot():
    if "user_id" not in session:
        return redirect("/login")
    user = db.session.get(User, session["user_id"])
    if not user:
        return redirect("/login")
    if session.get("whot_game"):
        flash("Finish or leave your current game first.")
        return game_ajax_response()
    try:
        stake = int(request.form.get("stake", 0))
    except (ValueError, TypeError):
        stake = 0
    if stake not in STAKES:
        flash("Choose a valid stake.")
        return game_ajax_response()
    if user.balance < stake:
        flash("Insufficient balance.")
        return game_ajax_response()
    user.balance -= stake
    session["whot_game"] = start_game(stake)
    session.modified = True
    db.session.commit()
    return game_ajax_response()


@app.route("/game/play", methods=["POST"])
def play_whot():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])
    game = session.get("whot_game")

    if not user or not game or game.get("finished"):
        return game_ajax_response()

    try:
        index = int(request.form.get("card_index", -1))
    except (ValueError, TypeError):
        index = -1

    valid, result = player_play(game, index, request.form.get("shape", ""))

    if not valid:
        flash(result)
        session["whot_game"] = game
        return game_ajax_response()

    game["ai_pending"] = False

    if result == "WIN":
        user.balance += game["prize"]
        game["message"] = "YOU WON! Winnings added: ₦" + str(game["prize"])
        game["finished"] = "won"
    elif result == "LOSE":
        game["message"] = "Your opponent won this round."
        game["finished"] = "lost"
    elif not game.get("extra_turn"):
        game["ai_pending"] = True

    session["whot_game"] = game
    session.modified = True
    db.session.commit()
    return game_ajax_response()


@app.route("/game/ai", methods=["POST"])
def ai_whot():
    if "user_id" not in session:
        return redirect("/login")

    from game_engine import bot_move
    game = session.get("whot_game")

    if not game or game.get("finished") or not game.get("ai_pending"):
        return game_ajax_response()

    time.sleep(0.20)
    bot_move(game)
    game["ai_pending"] = False

    if not game["bot"]:
        game["finished"] = "lost"
        game["message"] = "Your opponent won this round."

    session["whot_game"] = game
    session.modified = True
    return game_ajax_response()


@app.route("/game/draw", methods=["POST"])
def draw_whot():
    if "user_id" not in session:
        return redirect("/login")

    from game_engine import draw_cards
    game = session.get("whot_game")

    if not game or game.get("finished"):
        return game_ajax_response()

    draw_cards(game, game["player"], 1)
    game["extra_turn"] = False
    game["ai_pending"] = True
    game["message"] = "You picked a card. Your opponent's turn."

    session["whot_game"] = game
    session.modified = True
    return game_ajax_response()


@app.route("/game/leave", methods=["POST"])
def leave_whot():
    if "user_id" not in session:
        return redirect("/login")
    session.pop("whot_game", None)
    return game_ajax_response()


ADMIN_PASSWORD = os.environ.get("PLAYWHOT_ADMIN_PASSWORD", "Jimmy@19")

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect("/admin/dashboard")

    if request.method == "POST":
        password = request.form.get("password", "")
        if secrets.compare_digest(password, ADMIN_PASSWORD):
            session["admin_logged_in"] = True
            return redirect("/admin/dashboard")
        flash("Incorrect admin password.")

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>PLAYWHOT Admin Login</title>
      <style>
        body{background:#07130d;color:white;font-family:Arial;padding:25px}
        .box{max-width:400px;margin:80px auto;background:#10251a;padding:25px;border-radius:15px}
        input,button{width:100%;padding:14px;margin-top:12px;border:0;border-radius:8px;box-sizing:border-box}
        button{background:#00e676;color:#06130b;font-weight:bold}
      </style>
    </head>
    <body><div class="box">
      <h2>PLAYWHOT ADMIN</h2>
      {% for message in get_flashed_messages() %}<p>{{ message }}</p>{% endfor %}
      <form method="POST">
        <input type="password" name="password" placeholder="Admin password" required>
        <button type="submit">LOGIN</button>
      </form>
    </div></body></html>
    """)


@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    users = User.query.order_by(User.id.desc()).all()
    deposits = Deposit.query.order_by(Deposit.id.desc()).all()
    withdrawals = Withdrawal.query.order_by(Withdrawal.id.desc()).all()

    pending_deposits = sum(1 for d in deposits if d.status == "pending")
    pending_withdrawals = sum(1 for w in withdrawals if w.status == "pending")
    total_cash = sum(u.balance or 0 for u in users)

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PLAYWHOT | Admin</title>
<style>
:root {
  --green:#00ff88;
  --bg:#050b08;
  --panel:#0c1811;
  --border:rgba(0,255,136,.16);
  --muted:#91a99a;
}
*{box-sizing:border-box}
body{
  margin:0;background:radial-gradient(ellipse at top,#103522 0%,#07130c 42%,#030705 100%);
  color:#f2fff6;font-family:Arial,sans-serif;min-height:100vh;
}
header{
  padding:22px 5%;display:flex;justify-content:space-between;
  align-items:center;gap:12px;border-bottom:1px solid var(--border);
  background:rgba(4,15,9,.8);position:sticky;top:0;z-index:5;
  backdrop-filter:blur(14px);
}
.brand{font-size:21px;font-weight:900;letter-spacing:1px}
.brand span{color:var(--green);text-shadow:0 0 14px #00ff8877}
.admin-tag{color:var(--green);font-size:11px;letter-spacing:2px}
main{max-width:1150px;margin:auto;padding:25px 16px 50px}
.welcome{margin:12px 0 25px}
.welcome h1{font-size:27px;margin:0 0 8px}
.welcome p{color:var(--muted);margin:0;font-size:14px}
.stats{
  display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin-bottom:30px
}
.stat{
  background:linear-gradient(145deg,#10251a,#09140e);
  border:1px solid var(--border);border-radius:17px;padding:19px;
  box-shadow:0 0 22px rgba(0,255,136,.045);
}
.stat small{color:var(--muted);font-size:12px}
.stat strong{display:block;color:var(--green);font-size:25px;margin-top:12px;
  text-shadow:0 0 13px #00ff8844}
.section{margin-top:30px}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}
.section h2{font-size:17px;letter-spacing:.7px;margin:0}
.count{background:#123522;color:var(--green);padding:6px 10px;border-radius:20px;font-size:12px}
.item{
  background:linear-gradient(145deg,#102319,#0a150f);
  border:1px solid var(--border);border-radius:15px;
  padding:17px;margin:11px 0;box-shadow:0 7px 25px #0003;
}
.item-top{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}
.item h3{margin:0;font-size:15px}
.amount{font-size:20px;color:var(--green);font-weight:800}
.details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:15px 0}
.detail{background:#07130c;padding:10px;border-radius:9px;overflow-wrap:anywhere}
.detail small{display:block;color:var(--muted);font-size:10px;margin-bottom:5px}
.detail b{font-size:13px}
.status{font-size:10px;padding:6px 10px;border-radius:20px;text-transform:uppercase;
  background:#243329;color:#c8d9ce}
.status.pending{background:#443416;color:#ffd66b}
.status.approved{background:#103d27;color:#00ff88}
.status.rejected{background:#451d20;color:#ff8585}
.actions{display:flex;gap:9px;margin-top:14px}
button{
  border:0;border-radius:9px;padding:12px 17px;font-weight:800;
  cursor:pointer;transition:.2s;font-size:12px
}
button:active{transform:scale(.97)}
.approve{background:var(--green);color:#032011;box-shadow:0 0 15px #00ff8844}
.reject{background:#351719;color:#ff8888;border:1px solid #77363b}
.logout{background:#14271b;color:var(--green);border:1px solid var(--border)}
.empty{
  padding:24px;text-align:center;color:var(--muted);
  background:#0b1710;border:1px dashed var(--border);border-radius:13px
}
.notice{background:#102b1c;border:1px solid var(--border);padding:12px;border-radius:10px;
  color:var(--green);margin-bottom:15px;font-size:13px}
.user-row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.user-row p{margin:5px 0;color:var(--muted);font-size:12px}
footer{text-align:center;color:#607969;font-size:11px;padding:20px}
@media(max-width:700px){
  header{padding:17px 16px}
  .stats{grid-template-columns:repeat(2,1fr);gap:10px}
  .stat{padding:15px}
  .stat strong{font-size:21px}
  .welcome h1{font-size:23px}
}
@media(max-width:390px){
  .details{grid-template-columns:1fr}
  .actions button{flex:1;padding:12px 7px}
}
</style>
</head>
<body>
<header>
  <div class="brand">PLAY<span>WHOT</span></div>
  <div class="admin-tag">ADMIN CONTROL</div>
</header>

<main>
  <div class="welcome">
    <h1>Dashboard Overview</h1>
    <p>Manage users, deposits and withdrawals from one place.</p>
  </div>

  {% for message in get_flashed_messages() %}
    <div class="notice">{{ message }}</div>
  {% endfor %}

  <div class="stats">
    <div class="stat"><small>TOTAL USERS</small><strong>{{ users|length }}</strong></div>
    <div class="stat"><small>PENDING DEPOSITS</small><strong>{{ pending_deposits }}</strong></div>
    <div class="stat"><small>PENDING WITHDRAWALS</small><strong>{{ pending_withdrawals }}</strong></div>
    <div class="stat"><small>USERS' CASH BALANCE</small><strong>₦{{ "{:,}".format(total_cash) }}</strong></div>
  </div>

  <section class="section">
    <div class="section-head">
      <h2>DEPOSIT REQUESTS</h2>
      <span class="count">{{ deposits|length }} TOTAL</span>
    </div>
    {% for d in deposits %}
    <div class="item">
      <div class="item-top">
        <h3>Deposit #{{ d.id }} · {{ d.user.username if d.user else "Unknown user" }}</h3>
        <span class="status {{ d.status }}">{{ d.status }}</span>
      </div>
      <div class="details">
        <div class="detail"><small>AMOUNT</small><b class="amount">₦{{ "{:,}".format(d.amount) }}</b></div>
        <div class="detail"><small>SENDER NAME</small><b>{{ d.sender_name }}</b></div>
      </div>
      {% if d.status == "pending" %}
      <div class="actions">
        <form method="POST" action="/admin/deposit/{{ d.id }}/approve">
          <button class="approve">✓ APPROVE</button>
        </form>
        <form method="POST" action="/admin/deposit/{{ d.id }}/reject">
          <button class="reject">✕ REJECT</button>
        </form>
      </div>
      {% endif %}
    </div>
    {% else %}
    <div class="empty">No deposit requests yet.</div>
    {% endfor %}
  </section>

  <section class="section">
    <div class="section-head">
      <h2>WITHDRAWAL REQUESTS</h2>
      <span class="count">{{ withdrawals|length }} TOTAL</span>
    </div>
    {% for w in withdrawals %}
    <div class="item">
      <div class="item-top">
        <h3>Withdrawal #{{ w.id }} · {{ w.user.username if w.user else "Unknown user" }}</h3>
        <span class="status {{ w.status }}">{{ w.status }}</span>
      </div>
      <div class="details">
        <div class="detail"><small>AMOUNT</small><b class="amount">₦{{ "{:,}".format(w.amount) }}</b></div>
        <div class="detail"><small>BANK</small><b>{{ w.bank_name }}</b></div>
        <div class="detail"><small>ACCOUNT NAME</small><b>{{ w.account_name }}</b></div>
        <div class="detail"><small>ACCOUNT NUMBER</small><b>{{ w.account_number }}</b></div>
      </div>
      {% if w.status == "pending" %}
      <div class="actions">
        <form method="POST" action="/admin/withdrawal/{{ w.id }}/approve">
          <button class="approve">✓ APPROVE</button>
        </form>
        <form method="POST" action="/admin/withdrawal/{{ w.id }}/reject">
          <button class="reject">✕ REJECT</button>
        </form>
      </div>
      {% endif %}
    </div>
    {% else %}
    <div class="empty">No withdrawal requests yet.</div>
    {% endfor %}
  </section>

  <section class="section">
    <div class="section-head">
      <h2>REGISTERED USERS</h2>
      <span class="count">{{ users|length }} USERS</span>
    </div>
    {% for u in users %}
    <div class="item user-row">
      <div><h3>{{ u.fullname }}</h3><p>@{{ u.username }}</p></div>
      <div class="amount">₦{{ "{:,}".format(u.balance or 0) }}</div>
    </div>
    {% else %}
    <div class="empty">No registered users yet.</div>
    {% endfor %}
  </section>

  <form method="POST" action="/admin/logout" style="margin-top:30px">
    <button class="logout">↪ ADMIN LOGOUT</button>
  </form>
</main>
<footer>PLAYWHOT ADMIN PANEL · SECURE MANAGEMENT</footer>
</body>
</html>
    """, users=users, deposits=deposits, withdrawals=withdrawals,
       pending_deposits=pending_deposits,
       pending_withdrawals=pending_withdrawals,
       total_cash=total_cash)


@app.route("/admin/deposit/<int:deposit_id>/<action>", methods=["POST"])
def admin_deposit_action(deposit_id, action):
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    payment = db.session.get(Deposit, deposit_id)
    if not payment or payment.status != "pending":
        flash("Deposit request was already processed or does not exist.")
        return redirect("/admin/dashboard")

    if action == "approve":
        user = db.session.get(User, payment.user_id)
        if not user:
            flash("User not found. Deposit was not processed.")
            return redirect("/admin/dashboard")

        payment.status = "approved"
        user.balance = (user.balance or 0) + payment.amount
        reward_referrer_for_deposit(payment)
        flash("Deposit approved and cash balance updated.")
    elif action == "reject":
        payment.status = "rejected"
        flash("Deposit rejected. No balance was added.")
    else:
        return redirect("/admin/dashboard")

    db.session.commit()
    return redirect("/admin/dashboard")


@app.route("/admin/withdrawal/<int:withdrawal_id>/<action>", methods=["POST"])
def admin_withdrawal_action(withdrawal_id, action):
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    withdrawal = db.session.get(Withdrawal, withdrawal_id)
    if not withdrawal or withdrawal.status != "pending":
        flash("Withdrawal request was already processed or does not exist.")
        return redirect("/admin/dashboard")

    if action == "approve":
        user = db.session.get(User, withdrawal.user_id)
        if not user:
            flash("User not found. Withdrawal was not approved.")
            return redirect("/admin/dashboard")

        withdrawal.status = "approved"
        flash("Withdrawal approved. The amount was already deducted.")
    elif action == "reject":
        user = db.session.get(User, withdrawal.user_id)
        if not user:
            flash("User not found. Refund could not be processed.")
            return redirect("/admin/dashboard")

        user.balance = (user.balance or 0) + withdrawal.amount
        withdrawal.status = "rejected"
        flash("Withdrawal rejected. ₦" + str(withdrawal.amount) + " refunded to user.")
    else:
        return redirect("/admin/dashboard")

    db.session.commit()
    return redirect("/admin/dashboard")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


with app.app_context():
    db.create_all()
    from sqlalchemy import text
    with db.engine.begin() as connection:
        connection.execute(text(
            'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS '
            'game_balance INTEGER NOT NULL DEFAULT 70'
        ))


    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)

    user_columns = [c["name"] for c in inspector.get_columns("user")]
    deposit_columns = [c["name"] for c in inspector.get_columns("deposit")]

    with db.engine.begin() as connection:
        if "referral_code" not in user_columns:
            connection.execute(text(
                "ALTER TABLE \"user\" ADD COLUMN referral_code VARCHAR(20)"
            ))

        if "referred_by_id" not in user_columns:
            connection.execute(text(
                'ALTER TABLE "user" ADD COLUMN referred_by_id INTEGER '
                'REFERENCES "user"(id)'
            ))

        if "referral_rewarded" not in deposit_columns:
            connection.execute(text(
                "ALTER TABLE deposit ADD COLUMN referral_rewarded BOOLEAN "
                "NOT NULL DEFAULT FALSE"
            ))

    for existing_user in User.query.filter(
        User.referral_code.is_(None)
    ).all():
        existing_user.referral_code = secrets.token_hex(4).upper()

    db.session.commit()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
