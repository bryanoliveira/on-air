# TODO — On Air Event Hooks

1. [x] Design server-side hook layer triggered by logged events/state transitions.
2. [x] Add configurable Home Assistant light hook without hard-coded secrets.
3. [x] Implement first hook for `Living Room Bathroom Lights`:
   - red when a meeting is active and camera is in use;
   - green when a meeting is active with microphone only;
   - yellow/orange-ish from 18:00 through 01:00 after the meeting ends;
   - off otherwise when no meeting is active.
4. [x] Add tests for hook decisions and server behavior.
5. [x] Update README / `.env.example` with configuration and deployment notes.
6. [x] Run server tests locally.
7. [x] Review diff and prepare Atlas deployment approval card.

Deployment note: do not modify Atlas production service or Home Assistant state until Bryan explicitly approves the deployment step.
