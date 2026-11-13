import os
import secrets
import uuid
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session
from werkzeug.exceptions import HTTPException

from lottery import DrawError, new_draw, public_state, reveal_card, select_card, start_draw, update_draw
from storage import PostgresStore, PracticeStore


def create_app(store=None, shard_options=None, auth_service=None, game_accounts=None):
    app = Flask(__name__)
    on_render = os.getenv("RENDER") == "true"
    if on_render and not os.getenv("FLASK_SECRET_KEY"):
        raise RuntimeError("请在 Render 的 Environment 中设置 FLASK_SECRET_KEY。")
    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        instance = Path(app.instance_path)
        instance.mkdir(exist_ok=True)
        secret_path = instance / ".secret_key"
        if not secret_path.exists():
            try:
                with secret_path.open("x", encoding="utf-8") as f:
                    f.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        secret_key = secret_path.read_text(encoding="utf-8")
    app.config.update(SECRET_KEY=secret_key,
                      MAX_CONTENT_LENGTH=128 * 1024, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=on_render,
                      PERMANENT_SESSION_LIFETIME=timedelta(days=7))
    database = store if store is not None else PostgresStore()
    practice = PracticeStore()

    @app.before_request
    def protect():
        if request.path == "/healthz":
            return None
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(24)
        public = (request.endpoint == 'static' or request.path == '/login'
                  or request.path in ('/api/auth/me', '/api/auth/discord-link', '/api/auth/password-login'))
        if not public:
            user = app.extensions['current_user']()
            if not user:
                if request.path.startswith('/api/'):
                    return jsonify(error='请先登录。', redirect='/login'), 401
                return redirect('/login')
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                raise DrawError("页面验证已失效，请刷新页面后重试。", 403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        image_sources = "'self' data: https:" if request.path.startswith('/shards') or request.path in ('/my-fragments','/search-fragments','/admin/samples','/trades') else "'self' data:"
        response.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self'; img-src {image_sources}; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.errorhandler(DrawError)
    def draw_error(error):
        return jsonify(error=str(error)), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error="请求格式错误或地址不存在。"), error.code

    @app.route("/")
    def index():
        return render_template("index.html", csrf=session["csrf"])

    @app.get("/healthz")
    def healthz():
        # Render 存活检查不创建会话，也不公开名单或数据库连接信息。
        return jsonify(status="ok")

    @app.get("/api/health")
    def health():
        try:
            database.health()
            return jsonify(connected=True, message="Supabase 已连接")
        except DrawError as error:
            return jsonify(connected=False, message=str(error))

    def parse_id(draw_id):
        try:
            return str(uuid.UUID(draw_id))
        except ValueError:
            raise DrawError("无效的抽奖编号。", 404)

    @app.post("/api/draws")
    def create():
        payload = request.get_json()
        if not isinstance(payload, dict) or type(payload.get("practice", False)) is not bool:
            raise DrawError("提交的数据格式不正确。")
        state = new_draw(payload, practice=payload.get("practice", False))
        if state["practice"]:
            practice.create(state, session["csrf"])
        else:
            database.create(state)
        return jsonify(public_state(state)), 201

    @app.get("/api/draws")
    def history():
        return jsonify([public_state(s) for s in database.list()])

    @app.get("/api/draws/<draw_id>")
    def detail(draw_id):
        draw_id = parse_id(draw_id)
        state = practice.get(draw_id, session["csrf"]) if request.args.get("practice") == "1" else database.get(draw_id)
        return jsonify(public_state(state))

    @app.post("/api/draws/<draw_id>/<action>")
    def mutate(draw_id, action):
        draw_id = parse_id(draw_id)
        payload = request.get_json()
        if not isinstance(payload, dict) or type(payload.get("practice", False)) is not bool:
            raise DrawError("提交的数据格式不正确。")
        if action == "start":
            operation = start_draw
        elif action == "reveal":
            operation = lambda state: reveal_card(state, payload.get("index"))
        elif action == "select":
            operation = lambda state: select_card(state, payload.get("index"))
        elif action == "settings":
            operation = lambda state: update_draw(state, payload)
        else:
            raise DrawError("未知操作。", 404)
        if payload.get("practice", False):
            state = practice.mutate(draw_id, session["csrf"], operation)
        else:
            state = database.mutate(draw_id, operation)
        return jsonify(public_state(state))

    from auth_service import AuthService
    from auth_web import register_auth
    register_auth(app, auth_service if auth_service is not None else AuthService())
    from shards.accounts import GameAccounts
    from shards.accounts_web import register_accounts
    register_accounts(app, game_accounts if game_accounts is not None else GameAccounts())
    from shards.features_web import register_features
    register_features(app)
    from shards.trades_web import register_trades
    register_trades(app)
    from shards.web import create_blueprint
    app.register_blueprint(create_blueprint(**(shard_options or {})))
    return app


app = create_app()


def server_address():
    on_render = os.getenv("RENDER") == "true"
    host = "0.0.0.0" if on_render else os.getenv("HOST") or "127.0.0.1"
    port = int(os.getenv("PORT") or ("10000" if on_render else "5000"))
    return host, port


if __name__ == "__main__":
    from waitress import serve
    host, port = server_address()
    print(f"抽奖小屋已启动：http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=6)
