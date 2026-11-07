import os
import secrets
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from lottery import DrawError, new_draw, public_state, reveal_card, select_card, start_draw
from storage import PostgresStore, PracticeStore


def create_app(store=None):
    app = Flask(__name__)
    on_render = os.getenv("RENDER") == "true"
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if on_render:
        for name in ("FLASK_SECRET_KEY", "ADMIN_PASSWORD"):
            if not os.getenv(name):
                raise RuntimeError(f"请在 Render 的 Environment 中设置 {name}。")
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
                      SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=on_render)
    database = store if store is not None else PostgresStore()
    practice = PracticeStore()

    @app.before_request
    def protect():
        if request.path == "/healthz":
            return None
        if admin_password:
            auth = request.authorization
            authorized = (auth is not None and auth.type == "basic"
                          and secrets.compare_digest((auth.username or "").encode("utf-8"), b"admin")
                          and secrets.compare_digest((auth.password or "").encode("utf-8"), admin_password.encode("utf-8")))
            if not authorized:
                return app.response_class("请使用管理员账号登录。", status=401,
                    headers={"WWW-Authenticate": 'Basic realm="Lucky House", charset="UTF-8"'},
                    content_type="text/plain; charset=utf-8")
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(24)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                raise DrawError("页面验证已失效，请刷新页面后重试。", 403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
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
        else:
            raise DrawError("未知操作。", 404)
        if payload.get("practice", False):
            state = practice.mutate(draw_id, session["csrf"], operation)
        else:
            state = database.mutate(draw_id, operation)
        return jsonify(public_state(state))

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
