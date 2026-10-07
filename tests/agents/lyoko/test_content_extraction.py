"""Unit tests for LLM response content extraction and normalization."""

from dataclasses import dataclass

from lyoko.infrastructure.llm.content import extract_message_text


@dataclass
class DummyContentBlock:
    text: str


def test_extract_message_text_plain_string():
    assert extract_message_text("Hello world") == "Hello world"
    assert extract_message_text("") == ""
    assert extract_message_text(None) == ""


def test_extract_message_text_list_of_strings():
    assert extract_message_text(["Hello ", "world"]) == "Hello world"


def test_extract_message_text_list_of_dicts():
    content = [
        {
            "type": "text",
            "text": "Temperature: 50.85 °C",
            "annotations": [],
            "id": "msg_123",
        }
    ]
    assert extract_message_text(content) == "Temperature: 50.85 °C"


def test_extract_message_text_multiple_dict_blocks():
    content = [
        {"type": "text", "text": "Part 1\n"},
        {"type": "text", "text": "Part 2"},
    ]
    assert extract_message_text(content) == "Part 1\nPart 2"


def test_extract_message_text_stringified_python_representation():
    # Exactly matching the case seen in the incident screenshot
    raw_repr = (
        "[{'type': 'text', 'text': 'Aquí están las temperaturas actuales de las CPUs:\\n\\n"
        "1. Nodo: 192.168.33.48\\n - Sensor temp1: 50.85 °C', 'annotations': [], 'id': 'msg_0d94'}]"
    )
    result = extract_message_text(raw_repr)
    assert "Aquí están las temperaturas actuales" in result
    assert "50.85 °C" in result
    assert "msg_0d94" not in result
    assert "'annotations'" not in result
    assert not result.startswith("[{")


def test_extract_message_text_stringified_json_representation():
    json_repr = '[{"type": "text", "text": "CPU temp is 52 °C"}]'
    assert extract_message_text(json_repr) == "CPU temp is 52 °C"


def test_extract_message_text_object_with_text_attr():
    block = DummyContentBlock(text="Object text")
    assert extract_message_text(block) == "Object text"
    assert extract_message_text([block]) == "Object text"
