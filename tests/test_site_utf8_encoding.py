"""The docs builder reads and writes UTF-8 independently of the host locale."""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILD = textwrap.dedent("""\
    import importlib.util
    import json
    import locale
    from pathlib import Path
    import sys

    spec = importlib.util.spec_from_file_location("build_site", sys.argv[1])
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.OUT = Path(sys.argv[2])
    if len(sys.argv) > 3:
        builder.REPO = Path(sys.argv[3])
        builder.PAGES = {"README.md": "index.md", "docs/资料.md": "资料.md"}
    print(json.dumps({"encoding": locale.getpreferredencoding(False),
                      "utf8_mode": sys.flags.utf8_mode}), flush=True)
    builder.main()
""")


def run_builder(output, utf8_mode, source=None):
    """Run the actual builder with the native locale or Python's UTF-8 mode."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-B", "-X", f"utf8={utf8_mode}", "-c", BUILD,
               str(ROOT / "site" / "build_site.py"), str(output)]
    if source is not None:
        command.append(str(source))
    result = subprocess.run(command, env=env, capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[0])["utf8_mode"] == utf8_mode
    # Generated text files only; binary assets such as the paper PDF are copied as they are.
    for path in output.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".qmd", ".yml", ".css"}:
            path.read_bytes().decode("utf-8")


@pytest.mark.parametrize("utf8_mode", [0, 1])
def test_repository_pages_build_with_locale_and_utf8_modes(tmp_path, utf8_mode):
    output = tmp_path / "生成的文档 café"
    run_builder(output, utf8_mode)
    home = (output / "index.md").read_text(encoding="utf-8")
    # Every non-ASCII character of the README (such as "—") survives the build;
    # taken from the README itself, so editing its wording does not break this.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    non_ascii = {c for c in readme if ord(c) > 127}
    assert non_ascii
    assert non_ascii <= set(home)
    assert (output / "step4_cloud_removal.md").is_file()
    assert (output / "_quarto.yml").is_file()
    assert (output / "api" / "_sidebar.yml").is_file()


@pytest.mark.parametrize("utf8_mode", [0, 1])
def test_unicode_sources_titles_and_generated_navigation(tmp_path, utf8_mode):
    source = tmp_path / "仓库 café"
    (source / "docs").mkdir(parents=True)
    (source / "site").mkdir()
    title = "Café 卫星 🌍"
    detail_title = "Résumé 资料 🛰"
    (source / "README.md").write_text(
        f"# {title}\n\nA résumé — 中文 guide.\n\n[Details](docs/资料.md)\n",
        encoding="utf-8",
    )
    (source / "docs" / "资料.md").write_text(
        f"# {detail_title}\n\n中文说明 — données.\n", encoding="utf-8",
    )
    (source / "site" / "styles.css").write_text("/* café */\n", encoding="utf-8")
    output = tmp_path / "输出 🌍"
    run_builder(output, utf8_mode, source)

    home = (output / "index.md").read_text(encoding="utf-8")
    detail = (output / "资料.md").read_text(encoding="utf-8")
    navigation = (output / "_quarto.yml").read_text(encoding="utf-8")
    assert f'title: "{title}"' in home
    assert "A résumé — 中文 guide." in home
    assert "[Details](资料.html)" in home
    assert f'title: "{detail_title}"' in detail
    assert "中文说明 — données." in detail
    assert "href: 资料.md" in navigation
    assert f'text: "{detail_title}"' in navigation
    assert (output / "styles.css").read_bytes() == (source / "site" / "styles.css").read_bytes()
