from .indexer import match_templates, IndexHandle

def run_match(items, h: IndexHandle):
    return match_templates(items, h)
