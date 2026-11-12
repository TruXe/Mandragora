# Copy rubric (Layer B)

Layer A (`scanners/scan_copy.py`) matches vocabulary, punctuation and sentence patterns in prose.
Code spans and fenced blocks are skipped, so quoted examples in documentation do not count. This
rubric judges what patterns cannot see: whether each sentence carries a specific fact for a
specific reader. Use the files in `.recognitions/copy/` as few-shot examples.

## How to score

| Score | Meaning |
|-------|---------|
| 0 | Absent. |
| 1 | Trace: one instance in a long text. |
| 2 | Clear: the pattern recurs or sits in a headline or first paragraph. |
| 3 | Dominant: the text is built from the pattern. |

Pass threshold: every row scores 0 or 1, and every row whose recognition has severity 4 or 5
scores 0. Report the total. A slop element that fits no row goes to step S5.

## Rows

| Row | Signal to judge | Recognition | A score of 3 looks like |
|-----|-----------------|-------------|-------------------------|
| C1 | Verbs and adjectives promise an effect without naming the action | copy-hype-vocabulary | Every sentence has `elevate`, `seamless` or `unlock` |
| C2 | Clauses are bolted together with dashes | copy-dash-connector | Several em dashes or spaced hyphens per paragraph |
| C3 | Lists of three exist for rhythm, not content | copy-rule-of-three | Headline and subhead both built as triplets |
| C4 | Claims are framed against an alternative nobody raised | copy-negative-parallelism | `not just X, but Y` in the hero and the features |
| C5 | The opening sentence could start any text | copy-fast-paced-world-opener | `In today's fast-paced world` as the first words |
| C6 | Pictographs replace words at the start of list items | copy-emoji-bullets | Every bullet starts with an emoji |
| C7 | Superlatives appear without a number or a named comparison | copy-empty-superlatives | `industry-leading` and `best-in-class` with no data |
| C8 | The text avoids choosing a reader | copy-whether-you-are-hedge | `Whether you're a beginner or a pro` in the intro |
| C9 | The ending offers more instead of stating a final fact | copy-ready-to-get-started | `Ready to get started?` under every section |
| C10 | Headings use Title Case regardless of the product voice | copy-title-case-headings | Every heading capitalizes every word |
| C11 | The reply praises the question before answering | copy-sycophantic-opener | `Great question!` before each answer |
| C12 | Suspense is staged for an ordinary outcome | copy-question-reveal | `The result?` followed by a short punch line |

## Notes for judges

- Delete test: remove the sentence. If the reader loses no fact, the sentence scores toward
  C1, C3 or C7 even when no listed word appears.
- Read UI strings in context: a button label, an empty state and an error message each need the
  object and the next action, not encouragement.
- Layer A wins on presence: a fired rule means the row scores at least 1.
