import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/release-docs/scripts"))
from discover_release_sources import ProductionInputs, discover_release_sources  # noqa: E402


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "Project.csproj").write_text(
        '<Project><ItemGroup><PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.0" /></ItemGroup></Project>',
        encoding="utf-8")
    (tmp_path / "Migrations.cs").write_text(
        "class AppContext : DbContext {}\nclass AddThing : Migration {}\n",
        encoding="utf-8")
    (tmp_path / "baseline.sql").write_text("create table dbo.T(id int);", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-qm", "init"], check=True)
    return tmp_path


def test_only_three_required_inputs(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr("discover_release_sources._capabilities", lambda: {"SqlPackage": {"available": False}})
    result = discover_release_sources(ProductionInputs(repo, repo / "baseline.sql", "HEAD", "HEAD"))
    assert result.base_sha == result.target_sha
    assert any(item["path"] == "Project.csproj" for item in result.sources)
    assert result.capabilities["SqlPackage"]["available"] is False
    assert result.findings


def test_unknown_tool_does_not_delete_sources(tmp_path):
    repo = _repo(tmp_path)
    result = discover_release_sources(ProductionInputs(repo, repo / "baseline.sql", "HEAD", "HEAD"))
    assert result.sources
    assert "SqlPackage" in result.capabilities
