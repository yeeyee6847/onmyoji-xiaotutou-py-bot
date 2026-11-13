from flask import Blueprint, current_app, jsonify, render_template, request, session


def register_accounts(app, service):
    bp = Blueprint('game_accounts', __name__)
    app.extensions['game_accounts'] = service

    def player():
        return current_app.extensions['current_user']()['id']

    @bp.get('/game-accounts')
    def page():
        return render_template('game_accounts.html', csrf=session['csrf'])

    @bp.get('/api/game-accounts')
    def listing():
        return jsonify(service.list(player()))

    @bp.post('/api/game-accounts')
    def create():
        return jsonify(service.create(player(), request.get_json())), 201

    @bp.get('/api/game-accounts/<account_id>/fragments')
    def fragments(account_id):
        return jsonify(service.fragments(player(), account_id))

    app.register_blueprint(bp)
