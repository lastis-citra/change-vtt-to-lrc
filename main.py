import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path


TIMING_PATTERN = re.compile(
	r"^(?P<start>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+"
	r"(?P<end>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})(?P<settings>.*)$"
)
ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\ufeff]")
RUBY_READING_PATTERN = re.compile(r"(?<=[\u3400-\u9fff])\([^()]*[\u3040-\u30ff][^()]*\)")


@dataclass(frozen=True)
class Cue:
	start_ms: int
	end_ms: int
	settings: str
	text: str


def timestamp_to_milliseconds(timestamp: str) -> int:
	time_part, milliseconds = timestamp.split(".")
	parts = [int(part) for part in time_part.split(":")]
	if len(parts) == 3:
		hours, minutes, seconds = parts
		minutes += hours * 60
	else:
		minutes, seconds = parts
	return (minutes * 60 + seconds) * 1000 + int(milliseconds)


def format_timestamp(milliseconds: int) -> str:
	centiseconds = milliseconds // 10
	minutes, remainder = divmod(centiseconds, 6000)
	seconds, centiseconds = divmod(remainder, 100)
	return f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]"


def clean_text(text: str) -> str:
	text = html.unescape(re.sub(r"<[^>]*>", "", text))
	text = ZERO_WIDTH_PATTERN.sub("", text)
	text = RUBY_READING_PATTERN.sub("", text)
	text = text.translate(str.maketrans({"（": "(", "）": ")"}))
	return " ".join(text.split())


def parse_cues(content: str) -> list[Cue]:
	cues: list[Cue] = []
	seen: set[tuple[int, int, str, str]] = set()
	for block in re.split(r"\n[ \t]*\n", content):
		cue_lines = block.splitlines()
		for index, line in enumerate(cue_lines):
			match = TIMING_PATTERN.match(line.strip())
			if match is None:
				continue
			settings = match.group("settings").strip()
			text = clean_text(" ".join(cue_lines[index + 1 :]))
			if "line:0%" in settings or re.match(r"^(作詞|作曲|編曲|歌唱)[：:]", text):
				break
			start_ms = timestamp_to_milliseconds(match.group("start"))
			end_ms = timestamp_to_milliseconds(match.group("end"))
			key = (start_ms, end_ms, settings, text)
			if key not in seen:
				seen.add(key)
				if text:
					cues.append(Cue(start_ms, end_ms, settings, text))
			break
	return sorted(cues, key=lambda cue: cue.start_ms)


def line_setting(settings: str) -> str | None:
	match = re.search(r"(?:^|\s)line:([^, ]+)", settings)
	return match.group(1) if match else None


def can_merge(previous: Cue, current: Cue) -> bool:
	gap_ms = current.start_ms - previous.end_ms
	previous_line = line_setting(previous.settings)
	current_line = line_setting(current.settings)
	if previous_line is not None and previous_line == current_line and -750 <= gap_ms <= 750:
		return True
	if -100 <= gap_ms <= 100:
		return (
			previous.text == current.text
			or (len(previous.text) <= 2 and len(current.text) <= 2)
			or (len(previous.text) <= 2 and current.text.startswith(previous.text))
		)
	return False


def combine_text(cues: list[Cue]) -> str:
	parts: list[tuple[str, bool]] = []
	index = 0
	while index < len(cues):
		text = cues[index].text
		end = index + 1
		while end < len(cues) and cues[end].text == text:
			end += 1
		count = end - index
		is_short = len(text) <= 2
		if is_short:
			rendered = text * min(count, 8)
			if count > 8:
				rendered += "……"
			parts.append((rendered, True))
		else:
			parts.append((text, False))
		index = end

	result = ""
	previous_was_short = False
	for text, is_short in parts:
		if result and not (previous_was_short or is_short or text.startswith(result[-2:])):
			result += " "
		result += text
		previous_was_short = is_short
	return result


def convert_vtt(content: str) -> list[str]:
	cues = parse_cues(content)
	groups: list[list[Cue]] = []	
	for cue in cues:
		if groups and can_merge(groups[-1][-1], cue):
			groups[-1].append(cue)
		else:
			groups.append([cue])

	lines: list[str] = []
	for index, group in enumerate(groups):
		lines.append(f"{format_timestamp(group[0].start_ms)} {combine_text(group)}")
		if index + 1 < len(groups):
			gap_ms = groups[index + 1][0].start_ms - group[-1].end_ms
			if 0 < gap_ms <= 1000:
				lines.append(f"{format_timestamp(group[-1].end_ms)} ")
	return lines


def main() -> int:
	vtt_directory = Path(__file__).resolve().parent / "vtt"
	vtt_files = sorted(vtt_directory.glob("*.vtt"))
	if not vtt_files:
		print(f"VTTファイルが見つかりません: {vtt_directory}", file=sys.stderr)
		return 1

	output_lines: list[str] = []
	for vtt_file in vtt_files:
		content = vtt_file.read_text(encoding="utf-8-sig")
		output_lines.extend(convert_vtt(content))

	if output_lines:
		print("\n".join(output_lines))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
