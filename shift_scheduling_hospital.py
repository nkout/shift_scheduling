#!/usr/bin/env python3

from absl import app
from absl import flags
import os, tempfile
import webbrowser

from google.protobuf import text_format
from ortools.sat.python import cp_model
from pandas.core.array_algos.transforms import shift
from tabulate import tabulate

_OUTPUT_PROTO = flags.DEFINE_string(
    "output_proto", "", "Output file to write the cp_model proto to."
)
_PARAMS = flags.DEFINE_string(
    "params", "max_time_in_seconds:60.0", "Sat solver parameters."
)

html_header = '''<!DOCTYPE html>
<html>
<style>
table, th, td {
  border:1px solid black;
}
</style>
<body>

'''

html_footer = '''

</body>
</html>

'''

def solve_shift_scheduling(params: str, output_proto: str):
    """Solves the shift scheduling problem."""
    # Data
    num_employees = 50
    num_weeks = 4
    week = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    shifts = ["IM","M1", "M2", "IA", "A1", "A2", "N1", "N2"]

    shift_groups = [
        ["IM", "IA"],
        ["M1", "M2", "A1", "A2", "N1", "N2"]
    ]

    week_day_shifts = ["IA", "A1", "A2", "N1", "N2"]
    holiday_shifts = ["IM","M1", "M2", "IA", "A1", "A2", "N1", "N2"]

    levels = {
        "L01": ["IM", "IA"],
        "L02": ["IM", "IA", "M2", "A2"],
        "L03": ["IM", "IA", "M2", "A2", "N2"],
        "L04": ["M1", "M2", "IM", "IA", "A1", "A2", "N1", "N2"]
    }
    ################################################################################
    #start options
    month_first_day = "Th"
    month_days = 31
    public_holidays = [5, 6, 7]

    employees = [
        ("P01", "L01"),
        ("P02", "L01"),
        ("P03", "L01"),
        ("P04", "L01"),
        ("P05", "L02"),
        ("P06", "L02"),
        ("P07", "L02"),
        ("P08", "L02"),
        ("P05", "L02"),
        ("P09", "L03"),
        ("P10", "L03"),
        ("P11", "L03"),
        ("P12", "L03"),
        ("P13", "L03"),
        ("P14", "L03"),
        ("P15", "L04"),
        ("P16", "L04"),
        ("P17", "L04"),
        ("P18", "L04"),
        ("P19", "L04"),
        ("P20", "L04"),
#        ("P21", "L04"),
#        ("P22", "L04"),
    ]

#end options
################################################################################

    num_employees = len(employees)
    num_shifts = len(shifts)
    day_index = week.index(month_first_day)

    model = cp_model.CpModel()

    if not month_first_day in week:
        print("wrong day")
        return

    if month_days > 31 or month_days < 28:
        print("wrong month days")
        return

    for _, l in employees:
        if not l in levels:
            print ("wrong level " + l)
            return

    for l in levels:
        for s in levels[l]:
            if not s in shifts:
                print("wrong shift in level")
                return

    for s in week_day_shifts:
        if not s in shifts:
            print("wrong weekday shift")
            return

    for s in holiday_shifts:
        if not s in shifts:
            print("wrong holiday shift")
            return

    for h in public_holidays:
        if h > month_days or h <=0:
            print("wrong holiday")
            return

    for g in shift_groups:
        for s in g:
            if not s in shifts:
                print("wrong shift in group")
                return

    work = {}
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                work[e, s, d] = model.new_bool_var(f"work{e}_{s}_{d}")

    # Linear terms of the objective in a minimization context.
    obj_int_vars: list[cp_model.IntVar] = []
    obj_int_coeffs: list[int] = []
    obj_bool_vars: list[cp_model.BoolVarT] = []
    obj_bool_coeffs: list[int] = []

    # Exactly one shift per day.
    for e in range(num_employees):
        for d in range(month_days):
            model.add_at_most_one(work[e, s, d] for s in range(num_shifts))

    total_shifts = 0
    for d in range(month_days):
            is_holiday = False

            if d + 1 in public_holidays:
                is_holiday = True
            elif (d + day_index) % 7 in [5,6]:
                is_holiday = True

            day_shifts = set(week_day_shifts)
            if is_holiday:
                day_shifts = set(holiday_shifts)

            day_shifts = day_shifts.intersection(set(shift_groups[d % len(shift_groups)]))

            for s in range(num_shifts):
                works = [work[e, s, d] for e in range(num_employees)]
                if shifts[s] in day_shifts:
                    model.add(1 == sum(works))
                    total_shifts += 1
                else:
                    model.add(0 == sum(works))

    avg_shifts = total_shifts // len(employees)
    rem_shifts = total_shifts % len(employees)

    avg_shifts_up_limit = avg_shifts
    if rem_shifts > 0:
        avg_shifts_up_limit += 1

    print("avg shifts: " + str(avg_shifts) + " " + str(rem_shifts))

    for e in range(num_employees):
        name = f"shifts_count({e})"
        shifts_count = model.new_int_var(avg_shifts, avg_shifts_up_limit, name)
        works = [work[e, s, d] for s in range(num_shifts) for d in range(month_days)]
        model.add(shifts_count == sum(works))

    # Objective
    model.minimize(
        sum(obj_bool_vars[i] * obj_bool_coeffs[i] for i in range(len(obj_bool_vars)))
        + sum(obj_int_vars[i] * obj_int_coeffs[i] for i in range(len(obj_int_vars)))
    )

    if output_proto:
        print(f"Writing proto to {output_proto}")
        with open(output_proto, "w") as text_file:
            text_file.write(str(model))

    # Solve the model.
    solver = cp_model.CpSolver()
    if params:
        text_format.Parse(params, solver.parameters)
    solution_printer = cp_model.ObjectiveSolutionPrinter()
    status = solver.solve(model, solution_printer)

    # Print solution.
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("SOLVED")
        if status == cp_model.OPTIMAL:
            print("OPTIMAL")

        output = []
        header = ["", ""]
        header += shifts

        output.append(header)

        for d in range(month_days):
            line = [d + 1, week[(d + day_index) %7]]
            for s in range(num_shifts):
                shift_given = False
                for e in range(num_employees):
                    if solver.boolean_value(work[e, s, d]):
                        line.append(employees[e][0])
                        shift_given = True
                if not shift_given:
                    line.append("")
            output.append(line)

        #print(tabulate(output, tablefmt="html"))
        tmp = tempfile.NamedTemporaryFile(mode='w', delete = False, suffix='.html')
        try:
            print(tmp.name)
            tmp.write(html_header)
            tmp.write(tabulate(output, tablefmt="html"))
            tmp.write(html_footer)
        finally:
            tmp.close()
            webbrowser.open('file://' + os.path.realpath(tmp.name))


def main(_):
    solve_shift_scheduling(_PARAMS.value, _OUTPUT_PROTO.value)


if __name__ == "__main__":
    app.run(main)
