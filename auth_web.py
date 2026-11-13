import secrets

from flask import Blueprint, g, jsonify, redirect, render_template, request, session

from lottery import DrawError


def register_auth(app, service):
    bp = Blueprint('auth', __name__)
    app.extensions['auth_service'] = service

    def current_user():
        if 'login_user' not in g:
            g.login_user = service.current(session.get('auth_token'))
        return g.login_user

    app.extensions['current_user'] = current_user

    def establish(token):
        old = session.get('auth_token')
        if old:
            service.logout(old)
        session.clear()
        session['csrf'] = secrets.token_hex(24)
        session['auth_token'] = token
        # A seven-day server session, also bounded by browser cookie lifetime.
        session.permanent = True
        return jsonify(redirect='/shards')

    def payload():
        value = request.get_json()
        if not isinstance(value, dict):
            raise DrawError('请求格式不正确。')
        return value

    @bp.get('/login')
    def login_page():
        return render_template('account.html', csrf=session['csrf'], account_page=False)

    @bp.get('/account')
    def account_page():
        if not current_user():
            return redirect('/login')
        return render_template('account.html', csrf=session['csrf'], account_page=True)

    @bp.get('/api/auth/me')
    def me():
        return jsonify(user=current_user())

    @bp.post('/api/auth/discord-link')
    def consume():
        service.rate_limit('link-ip:' + (request.remote_addr or 'unknown'), limit=30)
        return establish(service.consume_link(payload().get('token')))

    @bp.post('/api/auth/password-login')
    def password_login():
        data = payload()
        service.rate_limit('password-ip:' + (request.remote_addr or 'unknown'), limit=30)
        return establish(service.login_password(data.get('username'), data.get('password')))

    @bp.post('/api/auth/password')
    def password():
        if not current_user():
            raise DrawError('请先登录。', 401)
        data = payload()
        if data.get('password') != data.get('confirm_password'):
            raise DrawError('两次输入的密码不一致。')
        service.rate_limit('password-set:' + current_user()['id'])
        service.set_password(session.get('auth_token'), data.get('password'))
        return jsonify(saved=True, redirect='/shards')

    @bp.post('/api/auth/logout')
    def logout():
        service.logout(session.get('auth_token'))
        session.clear()
        return jsonify(redirect='/login')

    app.register_blueprint(bp)
