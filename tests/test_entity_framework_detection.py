"""EF evidence is read from a requested Git revision, never the checkout."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


sys.path.insert(0, str(Path(__file__).parents[1] / "skills/release-docs/scripts"))
from detect_entity_framework import detect_entity_framework


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout.decode().strip()


def fixture_repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "commit", "-qm", "fixture")
    return repo, git(repo, "rev-parse", "HEAD")


def scope(repo, revision):
    paths = git(repo, "ls-tree", "-r", "--name-only", revision).splitlines()
    return {"revision": revision, "paths": paths}


def test_detects_ef_core_context_and_provider_from_revision(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><ItemGroup><PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.7" /></ItemGroup></Project>',
        "AppContext.cs": 'class AppContext : DbContext { }\nservices.AddDbContext<AppContext>(o => o.UseSqlServer(configuration.GetConnectionString("MainDb")));',
        "appsettings.json": '{"ConnectionStrings":{"MainDb":"Server=localhost;Database=ReleaseDb;User Id=sa;Password=secret"}}',
        "Migrations/20240101000000_Initial.cs": 'class Initial : Migration { protected override void Up(MigrationBuilder migrationBuilder) {} }',
        "Migrations/20240101000000_Initial.Designer.cs": '[DbContext(typeof(AppContext))][Migration("20240101000000_Initial")] class InitialMetadata {}',
        "Migrations/AppContextModelSnapshot.cs": 'class AppContextModelSnapshot : ModelSnapshot { }',
    })
    (repo / "App.csproj").write_text('<Project><PackageReference Include="Microsoft.EntityFrameworkCore.Sqlite" Version="9.0.0" /></Project>')
    result = detect_entity_framework(repo, scope(repo, revision))
    assert (result.framework, result.version, result.provider) == ("EF Core", "8.0.7", "SQL Server")
    assert result.contexts == ["AppContext"]
    assert result.database_identity == "server=localhost;database=releasedb"
    assert result.blocking is False
    assert "Migrations/20240101000000_Initial.cs" in result.migration_paths
    assert any(item["path"] == "App.csproj" and item["revision"] == revision and item["sha256"] == hashlib.sha256(git(repo, "show", f"{revision}:App.csproj").encode()).hexdigest() for item in result.evidence)


def test_detects_ef6_context_and_provider_from_revision(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "packages.config": '<packages><package id="EntityFramework" version="6.4.4" /></packages>',
        "App.csproj": '<Project><Reference Include="EntityFramework.SqlServer" /></Project>',
        "Data.cs": 'class DataContext : DbContext { public DataContext() : base("name=MainDb") {} }',
        "App.config": '<configuration><connectionStrings><add name="MainDb" connectionString="Data Source=localhost;Initial Catalog=ReleaseDb;User ID=sa;Password=secret" /></connectionStrings></configuration>',
        "Migrations/20240101000000_Initial.cs": 'class Initial : DbMigration { public override void Up() {} }',
        "Migrations/20240101000000_Initial.Designer.cs": '[DbContext(typeof(DataContext))] class InitialMetadata : IMigrationMetadata { public string Id => "20240101000000_Initial"; }',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert (result.framework, result.version, result.provider) == ("EF6", "6.4.4", "SQL Server")
    assert result.contexts == ["DataContext"]
    assert result.database_identity == "server=localhost;database=releasedb"
    assert result.blocking is False


def test_blocks_conflicting_provider_or_version_evidence(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.7" /><PackageReference Include="Microsoft.EntityFrameworkCore.Sqlite" Version="9.0.0" /></Project>',
        "Data.cs": 'class DataContext : DbContext {}\nservices.AddDbContext<DataContext>(o => o.UseSqlServer(configuration.GetConnectionString("MainDb")));',
        "appsettings.json": '{"ConnectionStrings":{"MainDb":"Server=localhost;Database=ReleaseDb"}}',
        "Migrations/20240101000000_Initial.cs": 'class Initial : Migration {}',
        "Migrations/20240101000000_Initial.Designer.cs": '[DbContext(typeof(DataContext))][Migration("20240101000000_Initial")] class InitialMetadata {}',
        "Migrations/DataContextModelSnapshot.cs": 'class DataContextModelSnapshot : ModelSnapshot {}',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.blocking is True
    assert any("provider" in finding.lower() for finding in result.findings)
    assert any("version" in finding.lower() for finding in result.findings)


def test_blocks_unproven_context_database_identity(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.7" /></Project>',
        "Data.cs": 'class FirstContext : DbContext {}\nclass SecondContext : DbContext {}\nservices.AddDbContext<FirstContext>(o => o.UseSqlServer(configuration.GetConnectionString("MainDb")));',
        "appsettings.json": '{"ConnectionStrings":{"MainDb":"Server=localhost;Database=ReleaseDb"}}',
        "Migrations/20240101000000_Initial.cs": 'class Initial : Migration {}',
        "Migrations/20240101000000_Initial.Designer.cs": '[DbContext(typeof(FirstContext))][Migration("20240101000000_Initial")] class InitialMetadata {}',
        "Migrations/FirstContextModelSnapshot.cs": 'class FirstContextModelSnapshot : ModelSnapshot {}',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.blocking is True
    assert any("database identity" in finding.lower() for finding in result.findings)


def test_blocks_missing_migration_snapshot_and_unknown_provider(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore" Version="8.0.7" /></Project>',
        "Data.cs": 'class AppContext : DbContext {}',
        "Migrations/20240101000000_Initial.cs": 'class Initial : Migration {}',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.blocking is True
    assert any("provider" in finding.lower() for finding in result.findings)
    assert any("migration chain" in finding.lower() for finding in result.findings)


def test_reads_locked_package_version_and_blocks_unresolved_version(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="$(EfVersion)" /></Project>',
        "packages.lock.json": '{"version": 1, "dependencies": {"net8.0": {"Microsoft.EntityFrameworkCore.SqlServer": {"type": "Direct", "resolved": "8.0.7"}}}}',
        "Data.cs": 'class AppContext : DbContext {}\nservices.AddDbContext<AppContext>(o => o.UseSqlServer(config.GetConnectionString("MainDb")));',
        "appsettings.json": '{"ConnectionStrings":{"MainDb":"Server=localhost;Database=ReleaseDb"}}',
        "Migrations/20240101000000_Initial.cs": 'class Initial : Migration {}',
        "Migrations/20240101000000_Initial.Designer.cs": '[DbContext(typeof(AppContext))][Migration("20240101000000_Initial")] class InitialMetadata {}',
        "Migrations/AppContextModelSnapshot.cs": 'class AppContextModelSnapshot : ModelSnapshot {}',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.version == "8.0.7"
    assert result.blocking is False


def test_blocks_when_no_entity_framework_evidence(tmp_path):
    repo, revision = fixture_repo(tmp_path, {"README.md": "no database source"})
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.blocking is True
    assert any("unknown" in finding.lower() for finding in result.findings)


def test_shared_connection_name_without_resolved_database_is_not_proof(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.7" /></Project>',
        "Data.cs": 'class FirstContext : DbContext {} class SecondContext : DbContext {}\nservices.AddDbContext<FirstContext>(o => o.UseSqlServer(config.GetConnectionString("MainDb")));\nservices.AddDbContext<SecondContext>(o => o.UseSqlServer(config.GetConnectionString("MainDb")));',
        "Migrations/20240101000000_Initial.cs": 'class Initial : Migration {}',
        "Migrations/20240101000000_Initial.Designer.cs": '[DbContext(typeof(FirstContext))][Migration("20240101000000_Initial")] class InitialMetadata {}',
        "Migrations/FirstContextModelSnapshot.cs": 'class FirstContextModelSnapshot : ModelSnapshot {}',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.database_identity is None
    assert result.blocking is True


def test_blocks_when_migration_coverage_is_only_for_one_context(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.7" /></Project>',
        "Data.cs": 'class FirstContext : DbContext {} class SecondContext : DbContext {}\nservices.AddDbContext<FirstContext>(o => o.UseSqlServer(config.GetConnectionString("MainDb")));\nservices.AddDbContext<SecondContext>(o => o.UseSqlServer(config.GetConnectionString("MainDb")));',
        "appsettings.json": '{"ConnectionStrings":{"MainDb":"Server=localhost;Database=ReleaseDb"}}',
        "Migrations/20240101000000_Initial.cs": 'class Initial : Migration {}',
        "Migrations/20240101000000_Initial.Designer.cs": '[DbContext(typeof(FirstContext))][Migration("20240101000000_Initial")] class InitialMetadata {}',
        "Migrations/FirstContextModelSnapshot.cs": 'class FirstContextModelSnapshot : ModelSnapshot {}',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.blocking is True
    assert any("migration chain" in finding.lower() for finding in result.findings)


def test_comments_and_string_literals_do_not_establish_provider(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore" Version="8.0.7" /></Project>',
        "Data.cs": 'class AppContext : DbContext {} // UseSqlServer(config.GetConnectionString("MainDb"))\nstring example = "UseSqlServer(";',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.provider is None
    assert result.blocking is True


def test_commented_project_reference_does_not_establish_provider(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore" Version="8.0.7" /><!-- <PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.7" /> --></Project>',
        "Data.cs": 'class AppContext : DbContext {}',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.provider is None
    assert result.blocking is True


def test_unrelated_provider_call_does_not_establish_configuration(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore" Version="8.0.7" /></Project>',
        "Data.cs": 'class AppContext : DbContext {}',
        "Example.cs": 'class Example { void Demo() { option.UseSqlServer("sample"); } }',
    })
    result = detect_entity_framework(repo, scope(repo, revision))
    assert result.provider is None
    assert result.blocking is True


def test_collector_exposes_pinned_ef_evidence_without_secrets(tmp_path):
    repo, revision = fixture_repo(tmp_path, {
        "App.csproj": '<Project><PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.7" /></Project>',
        "Data.cs": 'class AppContext : DbContext {}\nservices.AddDbContext<AppContext>(o => o.UseSqlServer(config.GetConnectionString("MainDb")));',
        "appsettings.json": '{"ConnectionStrings":{"MainDb":"Server=localhost;Database=ReleaseDb;Password=secret"}}',
        "Migrations/20240101000000_Initial.cs": 'class Initial : Migration {}',
        "Migrations/20240101000000_Initial.Designer.cs": '[DbContext(typeof(AppContext))][Migration("20240101000000_Initial")] class InitialMetadata {}',
        "Migrations/AppContextModelSnapshot.cs": 'class AppContextModelSnapshot : ModelSnapshot {}',
    })
    (repo / "App.csproj").write_text('<Project><PackageReference Include="Microsoft.EntityFrameworkCore.Sqlite" Version="9.0.0" /></Project>')
    script = Path(__file__).parents[1] / "skills/release-docs/scripts/collect_release_evidence.py"
    run = subprocess.run([sys.executable, str(script), "--repo", str(repo), "--base", revision, "--target", revision, "--diff-mode", "direct"], check=True, capture_output=True)
    data = json.loads(run.stdout)
    assert data["entity_framework"]["database_identity"] == "server=localhost;database=releasedb"
    assert data["entity_framework"]["blocking"] is False
    assert data["source_scope"]["revision"] == revision
    assert "secret" not in run.stdout.decode()
    assert "9.0.0" not in run.stdout.decode()
