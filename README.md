# SeatPlan: exam seating with no clashes, replanned in seconds

**Hackathon problem statement: 9 (Exam seating with no clashes, replanned in seconds)**
Team: 2392608303-Avengers

## What it does
Takes students (with subjects), rooms (rows x columns) and invigilators, and produces:
- a seat-by-seat plan where no two same-subject students sit side by side or front to back
- an invigilator roster (one per 30 students, nobody in two halls)
- a plain-language log of every rule it had to bend and why (bent seats get a red outline)
- instant replanning when a room or invigilator drops out, with a count of how many students changed seat

An independent checker re-counts every rule on the final plan, so the "rule violations" number is not the planner marking its own homework.

## How to run
No install, no server. Open `seatplan/index.html` in any browser.
1. Press **Generate and plan** (set students, subjects, rooms, invigilators first if you like).
2. Pick a room under **Something dropped out**, press **Remove room and replan**. Same for an invigilator.
3. Try making the exam overfull (e.g. 400 students, 6 rooms) to see the planner report what it had to bend.

## How it works
1. Students are sorted by subject (biggest first) and dealt round-robin into rooms by capacity, so every hall gets a mix.
2. Each room is filled seat by seat, choosing the subject with most students left that does not match the left or front neighbour.
3. If nothing fits, a spare seat is left empty. Only a full room with a dominant subject forces a same-subject neighbour, and that is reported.
4. Invigilators are assigned to the largest rooms first; shortfalls are reported.

## Limits (honest)
Single exam session, demo data is generated, the heuristic is greedy rather than provably optimal.
