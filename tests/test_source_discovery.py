import subprocess
import pytest
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


def test_unknown_tool_does_not_delete_sources(tmp_path, monkeypatch):
    monkeypatch.setattr('discover_release_sources.shutil.which', lambda name: None)
    repo = _repo(tmp_path)
    result = discover_release_sources(ProductionInputs(repo, repo / "baseline.sql", "HEAD", "HEAD"))
    assert result.sources
    assert "SqlPackage" in result.capabilities
    assert all(item['probe_status'] == 'not_found' for item in result.capabilities.values())


def test_real_version_probe_reports_verified_capability(monkeypatch):
    import discover_release_sources as discovery
    monkeypatch.setattr(discovery.shutil, 'which', lambda name: sys.executable)
    result = discovery._capabilities()
    assert all(item['available'] and item['probe_status'] == 'verified' for item in result.values())
    assert all(item['version'].startswith('Python ') for item in result.values())


@pytest.mark.parametrize('error,expected_status', [
    (subprocess.TimeoutExpired('probe', 10), 'timeout'), (OSError('cannot start'), 'error')])
def test_failed_tool_probe_retains_sources_and_reports_unavailable(tmp_path, monkeypatch, error, expected_status):
    import discover_release_sources as discovery
    repo = _repo(tmp_path)
    real_run = discovery.subprocess.run
    monkeypatch.setattr(discovery.shutil, 'which', lambda name: '/fixture/dotnet' if name == 'dotnet' else None)
    def run(command, **options):
        if command == ['/fixture/dotnet', '--version']:
            raise error
        return real_run(command, **options)
    monkeypatch.setattr(discovery.subprocess, 'run', run)
    result = discovery.discover_release_sources(ProductionInputs(repo, repo / 'baseline.sql', 'HEAD', 'HEAD'))
    assert any(item['path'] == 'Project.csproj' for item in result.sources)
    assert result.capabilities['dotnet']['available'] is False
    assert result.capabilities['dotnet']['probe_status'] == expected_status
    assert result.capabilities['SqlPackage']['available'] is False


def test_nonzero_probe_is_not_verified_tool(monkeypatch):
    import discover_release_sources as discovery
    monkeypatch.setattr(discovery.shutil, 'which', lambda name: '/fixture/tool')
    monkeypatch.setattr(discovery.subprocess, 'run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, b'', b'probe failed'))
    result = discovery._capabilities()
    assert all(item['available'] is False and item['probe_status'] == 'failed' for item in result.values())
