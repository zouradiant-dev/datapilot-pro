import hashlib
import io
import json
import runpy
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from datapilot.cli import main
from datapilot.ingestion.confirmation import confirm_file, confirm_schema
from datapilot.ingestion.contracts import (
    ColumnOverride,
    ConfirmationOverrides,
    ParseFailure,
    ParseOptions,
    SchemaConfirmation,
    SchemaProposal,
)
from datapilot.ingestion.parser import parse_bytes, parse_file
from datapilot.ingestion.profiling import propose_schema

FIXTURES = Path(__file__).parent / "fixtures/ingestion"


@pytest.mark.parametrize("zip_creator_system", [0, 3], ids=["windows", "unix"])
def test_committed_fixtures_are_synthetic_hashed_and_reproducible(monkeypatch, zip_creator_system):
    # scripts/ is a repository utility, not an installed application package.
    script = Path(__file__).resolve().parents[1] / "scripts/generate_ingestion_fixtures.py"
    build_fixtures = runpy.run_path(str(script))["build_fixtures"]
    original_init = zipfile.ZipInfo.__init__

    def platform_zip_info(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.create_system = zip_creator_system

    monkeypatch.setattr(zipfile.ZipInfo, "__init__", platform_zip_info)

    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    generated = build_fixtures()
    assert generated == build_fixtures()
    for name, expected in manifest["files"].items():
        data = (FIXTURES / name).read_bytes()
        assert data == generated[name]
        assert hashlib.sha256(data).hexdigest() == expected["sha256"]
        assert len(data) == expected["bytes"]


@pytest.mark.parametrize(
    "filename,table_count,row_count",
    [
        ("customers_utf8_bom.csv", 1, 3),
        ("invoices_semicolon.csv", 1, 3),
        ("saas_multi_sheet.xlsx", 3, 7),
    ],
)
def test_real_file_preview_to_confirmed_config(filename, table_count, row_count):
    path = FIXTURES / filename
    data = parse_file(path, options=ParseOptions(header="present"))
    preview = propose_schema(data)
    assert len(preview.tables) == table_count
    assert sum(t.row_count for t in preview.tables) == row_count
    confirmation = confirm_file(path, preview, reviewed=True)
    assert confirmation.source_sha256 == data.upload.sha256
    assert confirmation.proposal_sha256 == preview.proposal_sha256
    assert SchemaConfirmation.model_validate_json(confirmation.model_dump_json()) == confirmation


def test_candidate_relations_need_explicit_selection_and_full_validation():
    data = parse_file(FIXTURES / "saas_multi_sheet.xlsx", options=ParseOptions(header="present"))
    proposal = propose_schema(data)
    assert len(proposal.candidate_relations) == 1
    relation = proposal.candidate_relations[0]
    assert relation.child_table == "table_2" and relation.parent_table == "table_1"
    assert relation.matched_distinct_values == 2 and relation.requires_confirmation
    assert not confirm_schema(data, proposal, reviewed=True).accepted_relations
    confirmed = confirm_schema(
        data,
        proposal,
        reviewed=True,
        overrides=ConfirmationOverrides(
            primary_keys={"table_1": ["customer_id"]}, relation_ids=[relation.relation_id]
        ),
    )
    assert confirmed.accepted_relations == [relation]


def test_relation_types_are_checked_after_user_overrides():
    wb = Workbook()
    parent = wb.active
    parent.title = "Parents"
    parent.append(["customer_id"])
    parent.append([1])
    parent.append([2])
    child = wb.create_sheet("Children")
    for row in [["customer_id"], [1], [1], [2]]:
        child.append(row)
    stream = io.BytesIO()
    wb.save(stream)
    wb.close()
    data = parse_bytes(stream.getvalue(), "synthetic.xlsx", options=ParseOptions(header="present"))
    proposal = propose_schema(data)
    assert len(proposal.candidate_relations) == 1
    with pytest.raises(ParseFailure) as err:
        confirm_schema(
            data,
            proposal,
            reviewed=True,
            overrides=ConfirmationOverrides(
                columns=[
                    ColumnOverride(table_id="table_2", column="customer_id", logical_type="TEXT")
                ],
                relation_ids=[proposal.candidate_relations[0].relation_id],
            ),
        )
    assert err.value.error.code == "RELATION_INVALID"


def test_cli_preview_confirm_and_user_mapping_do_not_load_database_settings(
    monkeypatch, capsys, tmp_path
):
    def forbidden_settings(*args, **kwargs):
        raise AssertionError("Local preview must not require model or database credentials")

    monkeypatch.setattr("datapilot.cli.Settings", forbidden_settings)
    path = FIXTURES / "customers_utf8_bom.csv"
    proposal_path = tmp_path / "preview.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "datapilot",
            "ingest",
            "preview",
            str(path),
            "--header",
            "present",
            "--output",
            str(proposal_path),
        ],
    )
    assert main() == 0 and capsys.readouterr().out == ""
    proposal = SchemaProposal.model_validate_json(proposal_path.read_bytes())
    assert proposal.tables[0].columns[0].column.original_name == "客户编号"
    changes = tmp_path / "overrides.json"
    changes.write_text(
        json.dumps(
            {
                "columns": [
                    {
                        "table_id": "table_1",
                        "column": "column_1",
                        "normalized_name": "customer_id",
                        "logical_type": "TEXT",
                    }
                ],
                "primary_keys": {"table_1": ["column_1"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "datapilot",
            "ingest",
            "confirm",
            str(path),
            "--proposal",
            str(proposal_path),
            "--overrides",
            str(changes),
            "--reviewed",
        ],
    )
    assert main() == 0
    result = SchemaConfirmation.model_validate_json(capsys.readouterr().out)
    assert result.tables[0].primary_key == ["customer_id"]


def test_cli_fails_clearly_for_bad_options_review_and_stale_file(monkeypatch, capsys, tmp_path):
    source = tmp_path / "synthetic.csv"
    source.write_text("id\n001\n", encoding="utf-8")
    proposal = propose_schema(parse_file(source, options=ParseOptions(header="present")))
    config = tmp_path / "preview.json"
    config.write_text(proposal.model_dump_json(), encoding="utf-8")
    for suffix, expected in [
        (["preview", str(source), "--encoding", "made-up"], "CONFIG_INVALID"),
        (["confirm", str(source), "--proposal", str(config)], "REVIEW_REQUIRED"),
    ]:
        monkeypatch.setattr(sys, "argv", ["datapilot", "ingest", *suffix])
        assert main() == 2
        assert json.loads(capsys.readouterr().err)["error"]["code"] == expected
    source.write_text("id\n002\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["datapilot", "ingest", "confirm", str(source), "--proposal", str(config), "--reviewed"],
    )
    assert main() == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "PROPOSAL_STALE"


def test_output_files_are_not_overwritten(monkeypatch, capsys, tmp_path):
    destination = tmp_path / "keep.json"
    destination.write_text("preserved", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "datapilot",
            "ingest",
            "preview",
            str(FIXTURES / "customers_utf8_bom.csv"),
            "--output",
            str(destination),
        ],
    )
    assert main() == 2 and destination.read_text(encoding="utf-8") == "preserved"
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "OUTPUT_EXISTS"
