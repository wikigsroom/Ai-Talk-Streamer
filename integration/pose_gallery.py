"""Serve only explicitly reviewed pose photographs from a fixed manifest."""
import json
from aiohttp import web

LABELS={'welcome':'欢迎互动','explain':'摊手讲解','emphasis':'强调回应','listen':'倾听思考','posture':'坐姿调整','closing':'告别收尾'}

def configure_pose_gallery(app,root):
    def selected():
        path=root/'output/imagegen/motion-poses/delivery.json'
        if not path.exists():return []
        delivery=json.loads(path.read_text(encoding='utf-8'))
        reviews=json.loads((path.parent/'reviews.json').read_text(encoding='utf-8'))
        return [i for i in delivery['items'] if reviews.get(i['id'],{}).get('accepted')]

    async def catalog(request):
        items=[{'id':i['id'],'title':i['title'],'category':i['category'],'category_label':LABELS[i['category']],'native_size':i['native_size'],'url':'/materials/pose/'+i['id']+'.png','original_url':'/materials/pose-original/'+i['id']+'.png'} for i in selected()]
        return web.json_response({'count':len(items),'items':items},dumps=lambda value:json.dumps(value,ensure_ascii=False))

    async def picture(request):
        item=next((i for i in selected() if i['id']+'.png'==request.match_info['name']),None)
        if not item:raise web.HTTPNotFound()
        original=request.path.startswith('/materials/pose-original/')
        path=(root/item['native' if original else 'delivery']).resolve();path.relative_to(root)
        if not path.is_file():raise web.HTTPNotFound()
        headers={'Content-Disposition':'attachment; filename="'+item['id']+'.png"'} if original else {}
        return web.FileResponse(path,headers=headers)

    async def page(request):return web.FileResponse(root/'web/poses.html')
    app.router.add_get('/poses',page)
    app.router.add_get('/api/studio/poses',catalog)
    app.router.add_get('/materials/pose/{name}',picture)
    app.router.add_get('/materials/pose-original/{name}',picture)
