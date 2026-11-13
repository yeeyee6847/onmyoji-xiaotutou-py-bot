import io
from flask import Blueprint,current_app,jsonify,render_template,request,send_file,session
from lottery import DrawError
from shards.management import FragmentManagement
from shards.samples import SampleLibrary


def register_features(app):
    bp=Blueprint('features',__name__)
    service=FragmentManagement(app.extensions['game_accounts'].store)
    samples=SampleLibrary(app.extensions['game_accounts'].store)
    app.extensions['fragment_management']=service
    app.extensions['sample_library']=samples
    def user():return current_app.extensions['current_user']()
    def admin():
        if user()['role']!='admin':raise DrawError('此功能仅限 Admin。',403)

    @bp.get('/my-fragments')
    def mine_page():return render_template('workspace.html',csrf=session['csrf'],mode='mine')
    @bp.get('/search-fragments')
    def search_page():return render_template('workspace.html',csrf=session['csrf'],mode='search')
    @bp.get('/admin/samples')
    def sample_page():
        admin();return render_template('workspace.html',csrf=session['csrf'],mode='samples')
    @bp.get('/api/fragments')
    def search():
        mine=request.args.get('mine')=='1'
        return jsonify(service.search(shikigami_id=request.args.get('shikigami_id') or None,
            target=request.args.get('target') or None,server=request.args.get('server',''),
            rarity=request.args.get('rarity') or None,
            mine=user()['id'] if mine else None,account=request.args.get('game_account_id') or None))
    @bp.get('/api/fragments/totals')
    def totals():return jsonify(service.totals())
    @bp.post('/api/fragments')
    def write():return jsonify(service.write(user()['id'],request.get_json()))
    @bp.get('/api/admin/samples')
    def listing():
        admin()
        try:page=int(request.args.get('page','1'))
        except ValueError:raise DrawError('无效的页数。') from None
        return jsonify(samples.listing(request.args.get('status','pending'),page))
    @bp.get('/api/admin/samples/<identity>/image')
    def image(identity):
        admin();return send_file(io.BytesIO(samples.image(identity,request.args.get('kind'))),mimetype='image/png')
    @bp.post('/api/admin/samples/<identity>')
    def review(identity):
        admin();return jsonify(samples.review(user()['id'],identity,request.get_json()))
    app.register_blueprint(bp)
