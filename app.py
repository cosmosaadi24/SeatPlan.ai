import io
import math
import time
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="SeatPlan AI", page_icon="🪑", layout="wide")

# ---------------------------- Demo data ----------------------------
def demo_data(n_students=60, n_exams=3, n_rooms=4, n_invigilators=8):
    start = datetime(2026, 10, 10, 9, 0)
    sessions = []
    for i in range(n_exams):
        s = start + timedelta(hours=2 * i)
        sessions.append((f"EX{i+1}", s, s + timedelta(hours=1, minutes=30)))

    students = []
    for i in range(n_students):
        # Each student is registered for one or two non-overlapping exam sessions.
        first = i % n_exams
        students.append({
            "student_id": f"S{i+1:03d}",
            "exam_id": sessions[first][0],
            "start_time": sessions[first][1].strftime("%Y-%m-%d %H:%M"),
            "end_time": sessions[first][2].strftime("%Y-%m-%d %H:%M"),
        })
        if n_exams > 1 and i % 3 == 0:
            second = (first + 1) % n_exams
            students.append({
                "student_id": f"S{i+1:03d}",
                "exam_id": sessions[second][0],
                "start_time": sessions[second][1].strftime("%Y-%m-%d %H:%M"),
                "end_time": sessions[second][2].strftime("%Y-%m-%d %H:%M"),
            })

    # Use wide rooms so the demo can seat multiple exam groups without adjacency clashes.
    rooms = []
    for i in range(n_rooms):
        rooms.append({"room_id": f"R{i+1}", "rows": 8, "cols": 10})
    invigilators = [{"invigilator_id": f"INV{i+1:02d}"} for i in range(n_invigilators)]
    return pd.DataFrame(students), pd.DataFrame(rooms), pd.DataFrame(invigilators)


def parse_and_validate(students_df, rooms_df, inv_df):
    required_students = {"student_id", "exam_id", "start_time", "end_time"}
    required_rooms = {"room_id", "rows", "cols"}
    required_inv = {"invigilator_id"}
    if not required_students.issubset(students_df.columns):
        raise ValueError("Registrations CSV must contain: student_id, exam_id, start_time, end_time.")
    if not required_rooms.issubset(rooms_df.columns):
        raise ValueError("Rooms CSV must contain: room_id, rows, cols.")
    if not required_inv.issubset(inv_df.columns):
        raise ValueError("Invigilators CSV must contain: invigilator_id.")

    students = students_df.copy()
    rooms = rooms_df.copy()
    inv = inv_df.copy()
    for col in ["student_id", "exam_id"]:
        students[col] = students[col].astype(str).str.strip()
        if (students[col] == "").any():
            raise ValueError(f"{col} cannot be blank.")
    if students[["student_id", "exam_id"]].duplicated().any():
        raise ValueError("Duplicate student_id + exam_id registration found.")
    students["start_time"] = pd.to_datetime(students["start_time"], errors="coerce")
    students["end_time"] = pd.to_datetime(students["end_time"], errors="coerce")
    if students[["start_time", "end_time"]].isna().any().any():
        raise ValueError("Some exam date/time values could not be parsed. Use YYYY-MM-DD HH:MM.")
    if (students["start_time"] >= students["end_time"]).any():
        raise ValueError("Every exam end_time must be after start_time.")

    # An exam ID must have exactly one interval.
    intervals = students.groupby("exam_id")[["start_time", "end_time"]].nunique()
    if (intervals > 1).any().any():
        raise ValueError("Each exam_id must have one consistent start_time/end_time interval.")

    # One student cannot have overlapping exam registrations.
    for sid, group in students.sort_values("start_time").groupby("student_id"):
        records = group.to_dict("records")
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                if records[j]["start_time"] >= records[i]["end_time"]:
                    break
                if records[i]["start_time"] < records[j]["end_time"] and records[j]["start_time"] < records[i]["end_time"]:
                    raise ValueError(f"Student {sid} is registered for overlapping exams.")

    rooms["room_id"] = rooms["room_id"].astype(str).str.strip()
    rooms["rows"] = pd.to_numeric(rooms["rows"], errors="coerce")
    rooms["cols"] = pd.to_numeric(rooms["cols"], errors="coerce")
    if rooms[["rows", "cols"]].isna().any().any() or (rooms[["rows", "cols"]] < 1).any().any():
        raise ValueError("Room rows and cols must be positive whole numbers.")
    if (rooms[["rows", "cols"]] % 1 != 0).any().any():
        raise ValueError("Room rows and cols must be whole numbers.")
    if rooms["room_id"].duplicated().any() or (rooms["room_id"] == "").any():
        raise ValueError("Room IDs must be unique and nonblank.")
    rooms["rows"] = rooms["rows"].astype(int)
    rooms["cols"] = rooms["cols"].astype(int)

    inv["invigilator_id"] = inv["invigilator_id"].astype(str).str.strip()
    inv = inv[inv["invigilator_id"] != ""].drop_duplicates("invigilator_id")
    if inv.empty:
        raise ValueError("Provide at least one invigilator.")
    return students, rooms, inv


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def seat_room(students, room):
    """Backtracking seating. Orthogonal neighbours may not share an exam ID."""
    rows, cols = int(room["rows"]), int(room["cols"])
    if len(students) > rows * cols:
        return None
    # Most frequent exams first helps prune; student order within each exam is stable.
    by_exam = {}
    for s in students:
        by_exam.setdefault(str(s["exam_id"]), []).append(s)
    for exam in by_exam:
        by_exam[exam].sort(key=lambda x: str(x["student_id"]))
    exam_order = sorted(by_exam, key=lambda e: (-len(by_exam[e]), e))
    # A checkerboard order is a useful first attempt; backtracking can choose any seat.
    seat_order = [(r, c) for r in range(rows) for c in range(cols)]
    grid = [[None for _ in range(cols)] for _ in range(rows)]
    nodes = 0
    node_limit = 150000

    def allowed(r, c, exam):
        if r > 0 and grid[r-1][c] is not None and str(grid[r-1][c]["exam_id"]) == exam:
            return False
        if c > 0 and grid[r][c-1] is not None and str(grid[r][c-1]["exam_id"]) == exam:
            return False
        if r + 1 < rows and grid[r+1][c] is not None and str(grid[r+1][c]["exam_id"]) == exam:
            return False
        if c + 1 < cols and grid[r][c+1] is not None and str(grid[r][c+1]["exam_id"]) == exam:
            return False
        return True

    def search(index):
        nonlocal nodes
        nodes += 1
        if nodes > node_limit:
            return False
        if index == len(students):
            return True
        # Pick the next exam pool with the most remaining students.
        choices = [e for e in exam_order if by_exam[e]]
        if not choices:
            return True
        exam = max(choices, key=lambda e: len(by_exam[e]))
        student = by_exam[exam][0]
        # Prefer seats with fewer same-exam neighbours and central-ish placement.
        candidates = []
        for r, c in seat_order:
            if grid[r][c] is None and allowed(r, c, exam):
                neighbours = 0
                for rr, cc in ((r-1,c),(r+1,c),(r,c-1),(r,c+1)):
                    if 0 <= rr < rows and 0 <= cc < cols and grid[rr][cc] is not None:
                        neighbours += 1
                candidates.append((neighbours, (r+c) % 2, r, c))
        candidates.sort()
        for _, _, r, c in candidates:
            grid[r][c] = student
            by_exam[exam].pop(0)
            if search(index + 1):
                return True
            by_exam[exam].insert(0, student)
            grid[r][c] = None
        return False

    if not search(0):
        return None
    assignments = []
    for r in range(rows):
        for c in range(cols):
            s = grid[r][c]
            if s is not None:
                assignments.append({
                    "student_id": str(s["student_id"]),
                    "exam_id": str(s["exam_id"]),
                    "start_time": s["start_time"],
                    "end_time": s["end_time"],
                    "room_id": str(room["room_id"]),
                    "seat_row": r + 1,
                    "seat_col": c + 1,
                    "seat": f"R{r+1}-C{c+1}",
                })
    return {"room": room, "grid": grid, "assignments": assignments}


def make_plan(students_df, rooms_df, inv_df, unavailable_rooms=None, unavailable_inv=None):
    unavailable_rooms = set(unavailable_rooms or [])
    unavailable_inv = set(unavailable_inv or [])
    students, rooms, inv = parse_and_validate(students_df, rooms_df, inv_df)
    rooms = rooms[~rooms["room_id"].astype(str).isin(unavailable_rooms)].copy()
    invigilators = [x for x in inv["invigilator_id"].astype(str).tolist() if x not in unavailable_inv]
    if rooms.empty:
        raise ValueError("No available rooms remain.")
    if not invigilators:
        raise ValueError("No available invigilators remain.")

    sessions = []
    for (start, end), group in students.groupby(["start_time", "end_time"]):
        sessions.append({"start": start, "end": end, "students": group.to_dict("records")})
    sessions.sort(key=lambda x: x["start"])

    all_plans = []
    for session in sessions:
        session_students = session["students"]
        # Use largest rooms first; each room holds one non-overlapping slice of the session.
        room_candidates = rooms.sort_values(by=["rows", "cols"], ascending=False).to_dict("records")
        remaining = session_students[:]
        session_plans = []
        while remaining:
            best = None
            for room in room_candidates:
                if any(p["room"]["room_id"] == room["room_id"] for p in session_plans):
                    continue
                capacity = int(room["rows"]) * int(room["cols"])
                subset = remaining[:min(capacity, len(remaining))]
                candidate = seat_room(subset, room)
                if candidate is not None:
                    best = candidate
                    break
            if best is None:
                # Try each available unused room with all remaining students that fit.
                capacities = sum(int(r["rows"]) * int(r["cols"]) for r in room_candidates
                                 if not any(p["room"]["room_id"] == r["room_id"] for p in session_plans))
                raise ValueError(
                    f"Could not create a valid seating layout for {session['start']}–{session['end']}. "
                    f"{len(remaining)} students remain; unused room capacity is {capacities}. "
                    "Add rooms, increase room dimensions, or reduce the session size."
                )
            session_plans.append(best)
            seated_ids = {a["student_id"] + "|" + a["exam_id"] for a in best["assignments"]}
            remaining = [s for s in remaining if s["student_id"] + "|" + s["exam_id"] not in seated_ids]
        all_plans.extend(session_plans)

    # Independent verification: no duplicate assignment and no orthogonal same-exam neighbours.
    assignments = [a for p in all_plans for a in p["assignments"]]
    assignment_df = pd.DataFrame(assignments)
    if assignment_df.empty:
        raise ValueError("No students were assigned.")
    if assignment_df[["student_id", "exam_id"]].duplicated().any():
        raise ValueError("Internal validation failed: duplicate assignment.")
    for p in all_plans:
        grid = p["grid"]
        for r in range(len(grid)):
            for c in range(len(grid[0])):
                s = grid[r][c]
                if s is None:
                    continue
                for rr, cc in ((r+1,c),(r,c+1)):
                    if rr < len(grid) and cc < len(grid[0]):
                        other = grid[rr][cc]
                        if other is not None and str(other["exam_id"]) == str(s["exam_id"]):
                            raise ValueError("Internal validation failed: adjacent same-exam seats.")
    # One invigilator per up to 30 students per room-session; each staff member used once per session.
    roster = []
    for session in sessions:
        plans = [p for p in all_plans if p["assignments"] and p["assignments"][0]["start_time"] == session["start"]]
        staff_cursor = 0
        for p in plans:
            n = len(p["assignments"])
            required = max(1, math.ceil(n / 30))
            assigned = invigilators[staff_cursor:staff_cursor + required]
            staff_cursor += len(assigned)
            roster.append({
                "room_id": p["room"]["room_id"],
                "start_time": session["start"],
                "end_time": session["end"],
                "students": n,
                "invigilators_required": required,
                "invigilators_assigned": ", ".join(assigned) if assigned else "SHORTAGE",
                "shortage": max(0, required - len(assigned)),
            })
    return assignment_df, all_plans, pd.DataFrame(roster), students, rooms, inv


# ---------------------------- UI ----------------------------
st.title("SeatPlan AI")
st.caption("Conflict-aware exam seating, room capacity checks, and quick replanning.")

with st.sidebar:
    st.header("Exam setup")
    source = st.radio("Data source", ["Built-in demo", "Upload CSV files"])
    if source == "Built-in demo":
        n_students = st.number_input("Students", min_value=6, max_value=500, value=60, step=6)
        n_exams = st.number_input("Exam sessions", min_value=2, max_value=6, value=3)
        n_rooms = st.number_input("Rooms", min_value=1, max_value=12, value=4)
        n_inv = st.number_input("Invigilators", min_value=1, max_value=40, value=8)
        students_df, rooms_df, inv_df = demo_data(int(n_students), int(n_exams), int(n_rooms), int(n_inv))
    else:
        students_file = st.file_uploader("Registrations CSV", type=["csv"])
        rooms_file = st.file_uploader("Rooms CSV", type=["csv"])
        inv_file = st.file_uploader("Invigilators CSV", type=["csv"])
        if students_file is None or rooms_file is None:
            st.info("Upload registrations and rooms CSV files to continue.")
            st.stop()
        students_df = pd.read_csv(students_file)
        rooms_df = pd.read_csv(rooms_file)
        inv_df = pd.read_csv(inv_file) if inv_file else pd.DataFrame({"invigilator_id": [f"INV{i+1:02d}" for i in range(8)]})

    st.divider()
    st.subheader("Replanning controls")
    room_ids = rooms_df["room_id"].astype(str).tolist() if "room_id" in rooms_df.columns else []
    inv_ids = inv_df["invigilator_id"].astype(str).tolist() if "invigilator_id" in inv_df.columns else []
    dead_rooms = st.multiselect("Unavailable rooms", room_ids)
    dead_inv = st.multiselect("Unavailable invigilators", inv_ids)
    generate = st.button("Generate / replan", type="primary", use_container_width=True)

with st.expander("Input format"):
    st.markdown(
        "**Registrations CSV:** `student_id, exam_id, start_time, end_time`  \n"
        "**Rooms CSV:** `room_id, rows, cols`  \n"
        "**Invigilators CSV:** `invigilator_id`  \n"
        "Use times like `2026-10-10 09:00`. Each exam ID must have one consistent interval."
    )

st.subheader("Current input preview")
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Registrations", len(students_df))
with c2:
    st.metric("Rooms listed", len(rooms_df))
with c3:
    st.metric("Invigilators listed", len(inv_df))
with st.expander("Preview registrations"):
    st.dataframe(students_df.head(20), use_container_width=True)
with st.expander("Preview rooms and invigilators"):
    st.dataframe(rooms_df, use_container_width=True)
    st.dataframe(inv_df, use_container_width=True)

if generate or "plan_data" not in st.session_state:
    try:
        started = time.perf_counter()
        assignment_df, room_plans, roster_df, clean_students, active_rooms, active_inv = make_plan(
            students_df, rooms_df, inv_df, dead_rooms, dead_inv
        )
        st.session_state.plan_data = {
            "assignments": assignment_df,
            "plans": room_plans,
            "roster": roster_df,
            "elapsed": (time.perf_counter() - started) * 1000,
            "students": clean_students,
        }
        st.session_state.plan_error = None
    except Exception as exc:
        st.session_state.plan_error = str(exc)
        st.session_state.plan_data = None

if st.session_state.get("plan_error"):
    st.error(st.session_state.plan_error)
elif st.session_state.get("plan_data"):
    result = st.session_state.plan_data
    assignments = result["assignments"]
    plans = result["plans"]
    roster = result["roster"]
    st.success(f"Plan generated and validated in {result['elapsed']:.1f} ms.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Students seated", assignments["student_id"].nunique())
    m2.metric("Rooms used", assignments["room_id"].nunique())
    m3.metric("Adjacency violations", 0)
    m4.metric("Invigilator shortages", int(roster["shortage"].sum()) if not roster.empty else 0)

    tab1, tab2, tab3 = st.tabs(["Seat map", "Assignments", "Invigilator roster"])
    with tab1:
        for i, p in enumerate(plans):
            label = f"{p['room']['room_id']} · {p['assignments'][0]['start_time']}–{p['assignments'][0]['end_time']}"
            with st.expander(label, expanded=(i == 0)):
                grid = p["grid"]
                view = []
                for r, row in enumerate(grid):
                    view.append([f"{cell['student_id']}\n{cell['exam_id']}" if cell else "—" for cell in row])
                st.dataframe(pd.DataFrame(view, index=[f"Row {i+1}" for i in range(len(view))],
                                          columns=[f"Seat {j+1}" for j in range(len(view[0]))]),
                             use_container_width=True)
    with tab2:
        st.dataframe(assignments.sort_values(["start_time", "room_id", "seat_row", "seat_col"]), use_container_width=True)
        st.download_button("Download seating assignments CSV",
                           assignments.to_csv(index=False).encode("utf-8"),
                           "seating_assignments.csv", "text/csv")
    with tab3:
        st.dataframe(roster, use_container_width=True)
        st.download_button("Download invigilator roster CSV",
                           roster.to_csv(index=False).encode("utf-8"),
                           "invigilator_roster.csv", "text/csv")
    st.download_button("Download all assignments CSV",
                       assignments.to_csv(index=False).encode("utf-8"),
                       "examseat_assignments.csv", "text/csv")
