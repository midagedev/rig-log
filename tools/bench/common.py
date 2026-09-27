"""The bench ledger's one reader and writer, and the facts every bench tool shares.

The ledger (data/bloomery-bench.tsv) and the seed (data/bloomery-bench-seed.tsv) are TSV files
whose first line names the columns; every reader goes through `read_table`, by column name. A
field the tools cannot fill is a named error (BenchError), never a blank or a guessed default.
"""
import hashlib
import os
import re

COLUMNS = [
    "date", "window", "anchor", "source", "source_sha256",
    "model", "file", "card", "setup",
    "arm", "engine", "engine_build", "flags",
    "metric", "size", "value", "rounds", "clean_rounds", "tags",
    "status", "status_reason", "bloomery_commit",
]
STATUSES = ("clean", "provisional", "lower-bound")
METRICS = ("decode", "prompt")
BLOOMERY = "bloomery"
FAIL = "FAIL"
LEDGER = "data/bloomery-bench.tsv"
SEED = "data/bloomery-bench-seed.tsv"
PAGE = "docs/bloomery-bench.md"

# The repository is public: no field may carry a private address, a tailnet name, a BMC detail, a
# GPU UUID or a box path. Every writer passes each field through `assert_public`.
# (Assembled from parts so that this file itself passes the repository's grep for those strings.)
PRIVATE = re.compile("|".join([r"192\.16" + "8", r"10" + r"0\.[0-9]+\.[0-9]", r"\.ts\.ne" + "t", "adm" + "in",
                               "GP" + "U-[0-9a-f]{8}", "/ro" + "ot", "/ho" + "me/"]))


class BenchError(Exception):
    """A named refusal: the message says which field, which file and why."""


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def assert_public(where, value):
    m = PRIVATE.search(value)
    if m:
        raise BenchError(f"{where}: {value!r} carries a private detail ({m.group(0)!r}); only file names, "
                         "GPU names and commits go into the ledger")


def assert_field(where, value):
    if value == "":
        raise BenchError(f"{where}: empty field")
    if "\t" in value or "\n" in value:
        raise BenchError(f"{where}: a tab or a newline in {value!r}")
    assert_public(where, value)


def read_table(path):
    """Rows of a ledger-format TSV as dicts, by the header's column names. The header must name
    exactly COLUMNS (order free); every field must be filled."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise BenchError(f"{path}: no header line")
    head = lines[0].split("\t")
    if sorted(head) != sorted(COLUMNS) or len(head) != len(COLUMNS):
        missing = sorted(set(COLUMNS) - set(head))
        extra = sorted(set(head) - set(COLUMNS))
        raise BenchError(f"{path}: header columns differ from the ledger's (missing {missing}, extra {extra})")
    rows = []
    for i, ln in enumerate(lines[1:], 2):
        f = ln.split("\t")
        if len(f) != len(head):
            raise BenchError(f"{path}:{i}: {len(f)} fields, the header names {len(head)}")
        row = dict(zip(head, f))
        for k in COLUMNS:
            assert_field(f"{path}:{i} column {k}", row[k])
        check_row(f"{path}:{i}", row)
        rows.append(row)
    return rows


def check_row(where, row):
    if row["status"] not in STATUSES:
        raise BenchError(f"{where}: status {row['status']!r} is not one of {STATUSES}")
    if row["metric"] not in METRICS:
        raise BenchError(f"{where}: metric {row['metric']!r} is not one of {METRICS}")
    if not re.fullmatch(r"\d{4}-\d\d-\d\d", row["date"]):
        raise BenchError(f"{where}: date {row['date']!r} is not YYYY-MM-DD")
    if not re.fullmatch(r"log/\d{4}-\d\d-\d\d\.md#[a-z0-9-]+", row["anchor"]):
        raise BenchError(f"{where}: anchor {row['anchor']!r} is not log/YYYY-MM-DD.md#slug")
    if not row["size"].isdigit():
        raise BenchError(f"{where}: size {row['size']!r} is not a whole number")
    if row["value"] != FAIL:
        for v in row["value"].split("|"):
            if not re.fullmatch(r"\d+(\.\d+)?", v):
                raise BenchError(f"{where}: value {row['value']!r} is neither a number, `a|b|…` nor FAIL")
    if row["status"] != "clean" and row["status_reason"] == "-":
        raise BenchError(f"{where}: status {row['status']} without a reason")


def write_table(path, rows, append=False):
    for i, r in enumerate(rows):
        for k in COLUMNS:
            assert_field(f"{path} new row {i + 1} column {k}", str(r[k]))
        check_row(f"{path} new row {i + 1}", r)
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    mode = "a" if append and exists else "w"
    with open(path, mode, encoding="utf-8") as fh:
        if mode == "w":
            fh.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[k]) for k in COLUMNS) + "\n")


def row_value(row):
    """The row's number: the ledger's value, or for a seed row that lists the rounds its section
    states (`a|b`), their mean. None for a FAIL row."""
    if row["value"] == FAIL:
        return None
    vals = [float(v) for v in row["value"].split("|")]
    return sum(vals) / len(vals)


def model_of(file_name):
    """The model a file holds: its name without the shard suffix, the extension and the
    quantization tag. A name this cannot read is an error, not a guess."""
    stem = re.sub(r"\.gguf$", "", file_name)
    stem = re.sub(r"-\d{5}-of-\d{5}$", "", stem)
    for pat in (r"-(UD-)?(I?Q\d(_[0-9A-Z]+)*|BF16|F16)$", r"-exl3-\d+(\.\d+)?$"):
        m = re.search(pat, stem)
        if m:
            return stem[:m.start()]
    raise BenchError(f"model_of: {file_name!r} names no quantization this tool knows "
                     "(Q<n>_…, UD-Q<n>_…, BF16, F16, -exl3-<bpw>)")


def section(root, anchor):
    """The anchored section of a rig-log day file: from its `<a name>` to the next one."""
    path, slug = anchor.split("#", 1)
    full = os.path.join(root, path)
    if not os.path.exists(full):
        raise BenchError(f"anchor {anchor}: {path} does not exist")
    text = open(full, encoding="utf-8").read()
    tag = f'<a name="{slug}"></a>'
    i = text.find(tag)
    if i < 0:
        raise BenchError(f"anchor {anchor}: no `{tag}` in {path}")
    j = text.find("<a name=", i + len(tag))
    return text[i:j if j >= 0 else len(text)]


def section_sha(root, anchor):
    # rstrip: a section appended after this one must not move its hash through the blank lines between.
    return hashlib.sha256(section(root, anchor).rstrip().encode("utf-8")).hexdigest()[:16]


STRUCK = re.compile(r"~~.*?~~", re.S)


def stated(text, value):
    """Whether `value` is written in `text` outside a strike-through, verbatim or with thousands
    separators (5303.8 as 5,303.8), and not as the head of a longer number (30.7 in 30.71)."""
    live = STRUCK.sub(" ", text)
    whole, _, frac = value.partition(".")
    forms = {value}
    if len(whole) > 3:
        grouped = f"{int(whole):,}"
        forms.add(grouped + ("." + frac if frac else ""))
    for f in forms:
        if re.search(r"(?<![\d.,])" + re.escape(f) + r"(?![\d]|\.\d|,\d)", live):
            return True
    return False


def verify_seed_row(root, where, row):
    """A seed row's every value string must be stated in its anchor's section, and the section
    must be the one the row was checked against (its sha256 prefix)."""
    if row["source"] != "seed":
        raise BenchError(f"{where}: a seed row's source is `seed`, not {row['source']!r}")
    sha = section_sha(root, row["anchor"])
    if sha != row["source_sha256"]:
        raise BenchError(f"{where}: section {row['anchor']} changed since the row was checked "
                         f"(sha256 {row['source_sha256']} -> {sha}); read it again, then update the row's source_sha256")
    text = section(root, row["anchor"])
    if row["value"] == FAIL:
        return
    for v in row["value"].split("|"):
        if not stated(text, v):
            raise BenchError(f"{where}: value {v} is not stated in {row['anchor']} (outside strike-through)")
    if model_of(row["file"]) != row["model"]:
        raise BenchError(f"{where}: model {row['model']!r} is not the file's ({model_of(row['file'])!r})")
