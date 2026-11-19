# Newsie

Newsie is an event-centred news desk for German and Berlin political reporting. The event is the object a reader opens. Articles are evidence about that event. Publishers stay distinct voices. Claims stay tied to the passage they came from.

The product helps a reader see what is known, what is only claimed, where accounts differ, and what is still unclear. It does not tell the reader what to think, and it does not score publishers on a political axis.

## What the edition is allowed to say

- A sentence that states a development needs a stored article and a passage that supports it, directly or in part. A passage that only shares the subject is context, and the sentence fails validation.
- An attributed claim stays attributed. An allegation, prediction, analysis, or opinion is not written as an established fact.
- One origin repeated by several outlets is still one origin. Repetition is not independent corroboration.
- Counts of articles, publishers, and origins describe this collected sample. They are not public attention and they are not public opinion.
- Nothing is published until a person approves the draft.

## What decides that two articles are one event

Similar embeddings can propose a join. They cannot make it. The articles also have to share an occurrence: actors, a place, or the wording of what happened. If they do not, Newsie opens a separate event and records the rejected neighbour so the assignment can be reviewed.

An event, an ongoing story, and a topic are not the same thing. The pipeline builds events. A rejected join can point at a nearby event. Topics from social posts stay a signal, not evidence.

## What is still out of the MVP

A knowledge graph, narrative-diffusion tracking, rhetorical scores, audience data, and historical comparison are not part of this workflow. The event board draws only the sample, the assignment notes, and the brief sections above.
