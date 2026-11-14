"""A pass can join the renderer solely through registration."""
from cake.core.registry import Pass, register_pass, _registry
from cake.render.renderer import Renderer
from cake.styles import load_style


def test_registered_pass_runs_between_bloom_and_finish():
    trace = []
    try:
        @register_pass('demo_650', 650)
        class Demo(Pass):
            reads, writes = ('bloom',), ()

            def setup(self, gl, width, height):
                pass

            def run(self, frame_ctx):
                assert 'bloom' in frame_ctx.textures
                trace.append('demo')

        renderer = Renderer(4, 4, False)
        try:
            renderer.set_style(load_style('none'))
            for name in ('bloom', 'finish'):
                stage = renderer._by_name[name]
                original = stage.run
                stage.run = lambda fc, name=name, original=original: (trace.append(name), original(fc))
            renderer._by_name['bloom'].enabled = lambda recipe, fc: True
            renderer.render(bytes(4 * 4 * 3), 0)
            assert trace == ['bloom', 'demo', 'finish']
        finally:
            renderer.release()
    finally:
        _registry.pop('demo_650', None)
