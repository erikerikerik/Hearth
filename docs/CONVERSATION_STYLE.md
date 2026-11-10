# How much Hearth says (P009)

Some days she wants a listener; other days she wants easy conversation. Hearth handles both in two layers.

## 1. The workshop tone vials (lasting)

The vials and cogs in the workshop (warmth, humor, depth, questions, directness, challenge) now reach the language model.
Before P009 they were saved but ignored; the reply length and question rate were fixed in `config/system_prompt.txt`.

`app/conversation_style.py` turns the saved tone into a few plain instructions appended to the system prompt under
"How to talk right now", plus a sentence cap. The thresholds are the same ones the workshop's sample reply uses, so the
preview moves the way the companion does.

| Average of depth, questions, humor | Length | Sentence cap |
|---|---|---|
| below 0.3 | one or two short sentences | 2 |
| 0.3 – 0.6 (the defaults land here, 0.45) | two or three short sentences | 3 |
| 0.6 and up | two to four short sentences | 4 |

At the default tone, Hearth now reflects the feeling behind what she says and asks a gentle, specific follow-up about
every other reply. That is slightly more engaging than the fixed P008 prompt ("one or two short sentences… often just
reflect back"), which was the change asked for after the first real test.

## 2. Asking out loud (for today)

Said at the start of a turn, these change the style until the end of the local day, across page reloads:

| She says | Mode |
|---|---|
| "Can you just listen today?", "I just need you to listen", "No questions today" | **listen**: one or two sentences, no questions unless she asks, no advice or opinions |
| "Let's chat", "Can we just talk?", "Talk to me", "I'm in the mood to chat" | **chat**: two to four sentences, small opinions and light observations of its own, interest in her day; follows her lead if things turn heavier |
| "Back to normal" | back to the workshop tone |

"Let's talk about my sister" or "Just listen to this song" do not switch anything. Hearth replies to the request
itself in the new style, so she hears that it landed. The mode is held in process memory only. It is never written to
the database and resets at midnight or when Hearth restarts.

## What does not change

- The safety order in `app/companion.py`: crisis turns get the deterministic reply and never reach the model, in every
  mode. A crisis sentence never changes the mode.
- The base prompt keeps every rule about diagnosis, therapist claims, self-harm, advice-with-consent and memory. The
  style text is appended after it and is tested never to contain wording that would weaken them.
- Memory notes work exactly as before.

## Not measured yet

Longer replies mean more speaking time per turn. The first sentence still starts as soon as it is written, so the time
until she hears Hearth should not change, but nobody has measured that on the M3 yet. `pace` (speech speed and
breathing room) is still only shown in the workshop and is not wired to Kokoro.
