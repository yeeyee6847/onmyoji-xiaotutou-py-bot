from flask import Blueprint,current_app,jsonify,render_template,request,session
from shards.trades import Trades
from lottery import DrawError


def register_trades(app):
    bp=Blueprint('trades',__name__);service=Trades(app.extensions['game_accounts'].store)
    app.extensions['trades']=service
    def user():return current_app.extensions['current_user']()['id']
    @bp.get('/trades')
    def page():return render_template('trades.html',csrf=session['csrf'])
    @bp.get('/trade-records')
    def records_page():
        return render_template('trade_records.html',admin=current_app.extensions['current_user']()['role']=='admin')
    @bp.get('/api/trade-records')
    def records():
        try:page=int(request.args.get('page','1'))
        except ValueError:raise DrawError('无效的页数。') from None
        rows=service.listing(user(),admin=current_app.extensions['current_user']()['role']=='admin',
                             record_status=request.args.get('status','accepted'),page=page)
        return jsonify(items=rows[:40],page=page,has_more=len(rows)>40)
    @bp.get('/api/trades/partners')
    def partners():return jsonify(service.partners(user()))
    @bp.get('/api/trades')
    def listing():return jsonify(service.listing(user(),request.args.get('mine')=='1',request.args.get('id'),request.args.get('shikigami_id'),
                                                admin=current_app.extensions['current_user']()['role']=='admin'))
    @bp.post('/api/trades')
    def create():
        current_app.extensions['auth_service'].rate_limit('trade-create:'+user(),limit=30)
        return jsonify(service.create(user(),request.get_json())),201
    @bp.post('/api/trades/<identity>/<action>')
    def action(identity,action):
        if action=='retry-notification':return jsonify(service.retry_notification(user(),identity))
        return jsonify(service.action(user(),identity,action))
    app.register_blueprint(bp)
