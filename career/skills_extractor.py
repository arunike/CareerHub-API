import re

# Common English stop words used to suppress noisy keyword extraction without
# requiring heavyweight NLP runtime dependencies in production.
COMMON_STOP_WORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'been', 'being', 'by', 'for',
    'from', 'in', 'into', 'is', 'it', 'its', 'of', 'on', 'or', 'that', 'the',
    'their', 'them', 'they', 'this', 'to', 'was', 'were', 'will', 'with',
    'you', 'your', 'we', 'our', 'us', 'he', 'she', 'his', 'her', 'i', 'me',
    'my', 'mine', 'ours', 'yours', 'ourselves', 'yourself', 'yourselves',
    'about', 'after', 'again', 'against', 'all', 'am', 'any', 'because',
    'before', 'between', 'both', 'but', 'can', 'did', 'do', 'does', 'doing',
    'down', 'during', 'each', 'few', 'further', 'had', 'has', 'have', 'having',
    'here', 'how', 'if', 'more', 'most', 'no', 'nor', 'not', 'off', 'once',
    'only', 'other', 'out', 'over', 'same', 'should', 'so', 'some', 'such',
    'than', 'then', 'there', 'these', 'those', 'through', 'too', 'under',
    'until', 'up', 'very', 'what', 'when', 'where', 'which', 'who', 'whom',
    'why', 'would',
}


def _tokenize_words(text: str) -> list[str]:
    # Keep common tech punctuation so tokens like `node.js`, `c++`, and `ci/cd`
    # still match the keyword dictionary without requiring external corpora.
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9.+#/-]*", text)


def _contains_keyword(text: str, keyword: str) -> bool:
    if ' ' in keyword:
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])", text) is not None
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def extract_skills_from_text(text: str, company: str = "", title: str = "") -> list[str]:
    if not text:
        return []

    # Massive predefined dictionary of valid tech skills to catch regardless of case
    tech_keywords = {
        'golang', 'python', 'java', 'javascript', 'typescript', 'react', 'vue', 'angular',
        'docker', 'kubernetes', 'aws', 'gcp', 'azure', 'sql', 'mysql', 'postgresql', 'mongodb',
        'redis', 'kafka', 'rabbitmq', 'graphql', 'rest', 'linux', 'unix', 'django', 'flask',
        'fastapi', 'spring', 'node.js', 'nodejs', 'express', 'html', 'css', 'sass', 'less',
        'tailwind', 'git', 'github', 'gitlab', 'bitbucket', 'jira', 'confluence', 'agile',
        'scrum', 'kanban', 'machine learning', 'deep learning', 'nlp', 'computer vision',
        'data science', 'pandas', 'numpy', 'scipy', 'scikit-learn', 'tensorflow', 'pytorch',
        'c++', 'c#', 'php', 'ruby', 'swift', 'kotlin', 'dart', 'flutter', 'react native',
        'prompt', 'llm', 'llms', 'openai', 'claude', 'ci/cd', 'tcp/ip', 'pl/sql', 'ux/ui',
        'bash', 'shell', 'grpc', 'terraform', 'ansible', 'jenkins',
    }

    # Generic corporate/tech words to aggressively ignore if picked up by extraction
    generic_job_words = {
        'software', 'engineer', 'developer', 'manager', 'bachelor', 'master', 'degree',
        'experience', 'years', 'team', 'project', 'system', 'application', 'business',
        'product', 'development', 'management', 'data', 'design', 'testing', 'support',
        'working', 'knowledge', 'understanding', 'using', 'strong', 'ability', 'skills',
        'required', 'preferred', 'plus', 'including', 'related', 'field', 'science',
        'computer', 'engineering', 'role', 'responsibilities', 'requirements', 'environment',
    }

    candidates: list[str] = []
    lower_text = text.lower()

    # 1. Catch all pre-defined tech keywords regardless of text capitalization,
    # including multi-word phrases such as `machine learning`.
    for keyword in sorted(tech_keywords, key=len, reverse=True):
        if _contains_keyword(lower_text, keyword):
            candidates.append(keyword)

    # 2. Strict uppercase acronyms plus common Apple platform names.
    strict_acronyms = re.findall(r'\b[A-Z]{2,5}s?\b', text)
    strict_acronyms += re.findall(r'\b(?:iOS|macOS|tvOS)\b', text)
    candidates.extend(strict_acronyms)

    # 3. Token-based pass to catch punctuated single-token technologies.
    for word in _tokenize_words(text):
        clean_word = word.lower().strip(',.()!?:;')
        if clean_word in tech_keywords:
            candidates.append(clean_word)

    unique_skills: list[str] = []
    seen = set()

    # Dynamic context from user args
    if company:
        seen.update(company.lower().split())
    if title:
        seen.update(title.lower().split())

    hardcoded_rejects = {
        'dm', 'us', 'usa', 'uk', 'hq', 'vp', 'ceo', 'cfo', 'cto', 'roi', 'kpi', 'okr', 'llc', 'inc', 'ltd',
        'opt', 'cpt', 'h1b', 'ead', 'pto', 'al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'fl', 'ga', 'hi',
        'id', 'il', 'in', 'ia', 'ks', 'ky', 'la', 'me', 'md', 'ma', 'mi', 'mn', 'ms', 'mo', 'mt', 'ne', 'nv',
        'nh', 'nj', 'nm', 'ny', 'nc', 'nd', 'oh', 'ok', 'or', 'pa', 'ri', 'sc', 'sd', 'tn', 'tx', 'ut', 'vt',
        'va', 'wa', 'wv', 'wi', 'wy', 'dc',
    }
    seen.update(hardcoded_rejects)
    seen.update(generic_job_words)
    seen.update(COMMON_STOP_WORDS)

    for candidate in candidates:
        clean_candidate = candidate.strip(' -,.*&^%$#@!()[]{}|<>/?`~')
        if clean_candidate.endswith('.') and not clean_candidate.lower().endswith('.js') and not clean_candidate.lower().endswith('.net'):
            clean_candidate = clean_candidate[:-1]

        display_candidate = clean_candidate
        if clean_candidate.lower() in tech_keywords:
            if clean_candidate.lower() in {'c++', 'c#', 'ci/cd', 'tcp/ip', 'ux/ui', 'pl/sql'}:
                display_candidate = clean_candidate.upper()
            elif clean_candidate.lower() == 'ios':
                display_candidate = 'iOS'
            elif len(clean_candidate) <= 3 and clean_candidate.lower() not in {'git', 'vue', 'css'}:
                display_candidate = clean_candidate.upper()
            elif ' ' in clean_candidate or '/' in clean_candidate or '.' in clean_candidate:
                display_candidate = ' '.join(
                    part.upper() if len(part) <= 3 and part.isalpha() else part.capitalize()
                    for part in clean_candidate.split()
                )
            else:
                display_candidate = clean_candidate.capitalize()
        elif re.match(r'^[A-Z]{2,5}s?$', clean_candidate):
            display_candidate = clean_candidate

        lower_candidate = display_candidate.lower()

        if len(lower_candidate) < 2 and lower_candidate not in {'c', 'r'}:
            continue
        if lower_candidate in seen:
            continue
        if re.match(r'^[\+\-\$\€\£]?\d+(?:[.,]\d+)?(?:[KkMmBb]|\%)?$', lower_candidate):
            continue

        seen.add(lower_candidate)
        unique_skills.append(display_candidate)

    return unique_skills[:20]
