from flask import Blueprint,current_app,jsonify,render_template,request,session
from shards.trades import Trades


def register_trades(app):
    bp=Blueprint('trades',__name__);service=Trades(app.extensions['game_accounts'].store)
    app.extensions['trades']=service
    def user():return current_app.extensions['current_user']()['id']
    @bp.get('/trades')
    def page():return render_template('trades.html',csrf=session['csrf'])
    @bp.get('/api/trades/partners')
    def partners():return jsonify(service.partners(user()))
    @bp.get('/api/trades')
    def listing():return jsonify(service.listing(user(),request.args.get('mine')=='1',request.args.get('id'),request.args.get('shikigami_id')))
    @bp.post('/api/trades')
    def create():
        current_app.extensions['auth_service'].rate_limit('trade-create:'+user(),limit=30)
        return jsonify(service.create(user(),request.get_json())),201
    @bp.post('/api/trades/<identity>/<action>')
    def action(identity,action):
        if action=='retry-notification':return jsonify(service.retry_notification(user(),identity))
        return jsonify(service.action(user(),identity,action))
    app.register_blueprint(bp)
