"""Token windows preserve original characters and never cross page/section boundaries."""
import hashlib

CHUNK_SIZE = 320
OVERLAP = 48
MAX_TOKENS = 512


def token_count(tokenizer, text):
    return len(tokenizer(text, add_special_tokens=True, truncation=False)['input_ids'])


def chunk_pages(pages, tokenizer):
    chunks = []
    for page in pages:
        section = page.get('section')
        prefix = (section.strip() + '\n') if section and section.strip() else ''
        # Table extraction repeats column names on each row. Keep each such row
        # intact, repeating preceding conditions on every row. A new prose block
        # changes the conditions for subsequent rows instead of mixing groups.
        text = page['text'].strip()
        blocks = []
        if ' | ' in text:
            pending, conditions = [], ''
            for line in text.splitlines():
                if ' | ' in line:
                    if pending:
                        conditions = '\n'.join(pending) + '\n'
                        pending = []
                    blocks.append((line, prefix + conditions))
                elif line.strip():
                    pending.append(line)
            if pending:
                blocks.append(('\n'.join(pending), prefix))
        else:
            blocks.append((text, prefix))
        for block, block_prefix in blocks:
            if not block.strip():
                continue
            reserve = len(tokenizer(block_prefix, add_special_tokens=False)['input_ids']) if block_prefix else 0
            budget = CHUNK_SIZE - reserve
            if budget <= OVERLAP:
                raise ValueError('SECTION_TOO_LONG')
            offsets = tokenizer(block, add_special_tokens=False, truncation=False,
                                return_offsets_mapping=True)['offset_mapping']
            if ' | ' in block and len(offsets) > budget:
                raise ValueError('TABLE_ROW_TOO_LONG')
            start = 0
            while start < len(offsets):
                end = min(start + budget, len(offsets))
                # Use offsets rather than decode(token IDs): exact source text,
                # accents, whitespace, headers and numbers survive chunking.
                value = block_prefix + block[offsets[start][0]:offsets[end - 1][1]]
                while (token_count(tokenizer, 'passage: ' + value) > MAX_TOKENS
                       or len(tokenizer(value, add_special_tokens=False)['input_ids']) > CHUNK_SIZE):
                    end -= 1
                    if end <= start + OVERLAP:
                        raise ValueError('CHUNK_BUDGET')
                    value = block_prefix + block[offsets[start][0]:offsets[end - 1][1]]
                kind = page.get('extraction_kind', 'native')
                chunks.append(dict(ordinal=len(chunks), text=value,
                    chunk_hash=hashlib.sha256(value.encode('utf-8')).hexdigest(),
                    page=page.get('page'), section=section, extraction_kind=kind,
                    numeric_eligible=kind == 'native' and page.get('numeric_eligible', True)))
                if end == len(offsets):
                    break
                start = end - OVERLAP
    if not chunks:
        raise ValueError('EMPTY_CHUNKS')
    return chunks
