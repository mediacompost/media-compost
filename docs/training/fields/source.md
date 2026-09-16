## Source

### Build prompts from

Every image needs a text prompt to train against, and this decides where that text comes from.

Tags give you control: they can be shuffled, sampled, balanced and dropped, which is what makes a model respond to individual words rather than to whole memorised sentences. Captions give you natural language and relationships between things (“a red car parked in front of a house”) that a tag list cannot express. Caption + tags puts the sentence first and the tag list after it, which is the usual choice when your library has both.

Nothing (trigger word only) is the fourth answer: every prompt is the trigger word and nothing else. That is how a trigger is taught to mean the pictures themselves rather than to modify something a prompt has already said — the usual choice for a style or a character where the pictures are the whole point and nothing about them varies in a way you want to be able to ask for. It is also the only source under which every selected picture is in the run whatever it carries, since there is nothing it could be missing; tag and caption selection do not apply. Without a trigger word it would train on an empty prompt, which is the dropout signal rather than a concept, so set one.

### Trigger word

A word put at the front of every training prompt, which you then type to summon what was trained. It works because the model binds what it sees to the words it is given.

Pick something the model has no prior opinion about: 'ohwx', 'sks style', an invented name. A common word like 'portrait' would blend your concept into everything that word already means. Leave it empty when you are teaching an existing concept rather than a new one.
