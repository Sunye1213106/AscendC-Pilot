from pathlib import Path
p = Path(__file__).with_name('apply_nested_type_resolution.py')
text = p.read_text()
text = text.replace("test_path.write_text(r'''from uo.scripts.type_normalizer import (", 'test_path.write_text(r"""from uo.scripts.type_normalizer import (')
text = text.replace("    ) == 'Buffer<int,float>'\n''')", "    ) == 'Buffer<int,float>'\n\"\"\")")
p.write_text(text)
