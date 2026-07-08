"""Tests for user-uploaded attachment extraction."""

from io import BytesIO

import pytest
from starlette.datastructures import Headers, UploadFile

from backend.models.research import SourceType
from backend.services.attachment_ingest import extract_attachment_sources


@pytest.mark.asyncio
async def test_extract_xml_xls_attachment_as_research_source():
    workbook = b"""<?xml version="1.0"?>
    <Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">
      <Worksheet ss:Name="Summary" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
        <Table>
          <Row>
            <Cell><Data ss:Type="String">Metric</Data></Cell>
            <Cell><Data ss:Type="String">Value</Data></Cell>
          </Row>
          <Row>
            <Cell><Data ss:Type="String">Revenue growth</Data></Cell>
            <Cell><Data ss:Type="String">42%</Data></Cell>
          </Row>
        </Table>
      </Worksheet>
    </Workbook>"""
    upload = UploadFile(
        filename="model.xls",
        file=BytesIO(workbook),
        headers=Headers({"content-type": "application/vnd.ms-excel"}),
    )

    sources = await extract_attachment_sources([upload])

    assert len(sources) == 1
    source = sources[0]
    assert source.source_type == SourceType.USER_ATTACHMENT
    assert source.relevance_score == pytest.approx(0.95)
    assert source.metadata["filename"] == "model.xls"
    assert "Revenue growth" in source.content
    assert "42%" in source.content
