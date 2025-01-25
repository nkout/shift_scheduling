#!/usr/bin/env python3

from absl import app
from absl import flags
import os, tempfile
import webbrowser

from google.protobuf import text_format
from ortools.sat.python import cp_model
from pandas.compat.numpy.function import validate_sum
from pandas.core.array_algos.transforms import shift
from tabulate import tabulate

_OUTPUT_PROTO = flags.DEFINE_string(
    "output_proto", "", "Output file to write the cp_model proto to."
)
_PARAMS = flags.DEFINE_string(
    "params", "max_time_in_seconds:30.0", "Sat solver parameters."
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

num_employees = 50
num_weeks = 4
week = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
shifts = ["IM", "M1", "M2", "IA", "A1", "A2", "A3","N1", "N2"]

shift_groups = [
    ["M1", "M2", "A1", "A2", "A3", "N1", "N2"],
    ["IM", "IA"]
]

week_day_shifts = ["IA", "A1", "A2", "A3", "N1", "N2"]
holiday_shifts = ["IM", "M1", "M2", "IA", "A1", "A2", "A3","N1", "N2"]

levels = {
    "L01": ["IM", "IA"],
    "L02": ["IM", "IA", "M2", "A3"],
    "L03": ["IM", "IA", "M2", "A2", "A3","N2"],
    "L04": ["M1", "M2", "IM", "IA", "A1", "A2", "A3","N1", "N2"]
}


# Data
################################################################################
#start options
month_first_day = "Sa"
month_days = 28
public_holidays = []
prev_month_last_is_holiday = False
next_month_first_is_holiday = False

employees = [
    ("P01", "L01", 0, ()),
    ("P02", "L01", 0, ()),
    ("P03", "L01",0, ()),
    ("P04", "L01", 0, ()),
    ("P05", "L02", 0, ()),
    ("P06", "L02", 0, ()),
    ("P07", "L02", 0, ()),
    ("P08", "L02", 0, ()),
    ("P09", "L03", 0, ()),
    ("P10", "L03", 0, ()),
    ("P11", "L03", 0, ()),
    ("P12", "L03", 0, ()),
    ("P13", "L03", 0, ()),
    ("P14", "L03", 0, ()),
    ("P15", "L04", 0, ()),
    ("P16", "L04", 0, ()),
    ("P17", "L04", 0, ()),
    ("P18", "L04", 0, ()),
    ("P19", "L04", 0, ()),
    ("P20", "L04", 0, ()),
    ("P21", "L04", 0, ()),
    ("P22", "L04", 0, ()),
    ("P23", "L04", 0, ()),
    ("P24", "L04", 0, ()),
    ("P25", "L04", 0, ()),
    ("P26", "L04", 0, ()),
    ("P27", "L04", 0, ()),
    ("P28", "L04", 0, ()),
#        ("P21", "L04"),
#        ("P22", "L04"),
]

#end options
################################################################################

def is_holiday(d):
    if d == -1:
        return prev_month_last_is_holiday
    if d == month_days:
        return next_month_first_is_holiday

    first_day_index = week.index(month_first_day)
    if d + 1 in public_holidays:
        return True
    elif (d + first_day_index) % 7 in [5, 6]:
        return True
    return False


def validate_input():
    valid = True

    if not month_first_day in week:
        print("wrong day")
        valid = False
    if month_days > 31 or month_days < 28:
        print("wrong month days")
        valid = False
    for _, l, _, neg in employees:
        if not l in levels:
            print("wrong level " + l)
            valid = False
        for n in neg:
            if n > month_days or n < 1:
                print("wrong negative")
                valid = False
    for l in levels:
        for s in levels[l]:
            if not s in shifts:
                print("wrong shift in level")
                valid = False
    for s in week_day_shifts:
        if not s in shifts:
            print("wrong weekday shift")
            valid = False
    for s in holiday_shifts:
        if not s in shifts:
            print("wrong holiday shift")
            valid = False
    for h in public_holidays:
        if h > month_days or h <= 0:
            print("wrong holiday")
            valid = False
    for g in shift_groups:
        for s in g:
            if not s in shifts:
                print("wrong shift in group")
                valid = False
    return valid


def print_solution(solver, status, work):
    num_employees = len(employees)
    num_shifts = len(shifts)
    first_day_index = week.index(month_first_day)

    if status == cp_model.OPTIMAL:
        print("OPTIMAL")
    output = []
    header = ["", ""]
    header += shifts
    output.append(header)
    for d in range(month_days):
        line = []
        if is_holiday(d):
            line.append('* ' + str(d + 1))
        else:
            line.append('  ' + str(d + 1))
        line.append(week[(d + first_day_index) % 7])
        for s in range(num_shifts):
            shift_given = False
            for e in range(num_employees):
                if solver.boolean_value(work[e, s, d]):
                    line.append(employees[e][0])
                    shift_given = True
            if not shift_given:
                line.append("")
        output.append(line)
    # print(tabulate(output, tablefmt="html"))
    tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html')
    try:
        print(tmp.name)
        tmp.write(html_header)
        tmp.write(tabulate(output, tablefmt="html"))
        tmp.write(html_footer)
    finally:
        tmp.close()
        webbrowser.open('file://' + os.path.realpath(tmp.name))



def solve_shift_scheduling(params: str, output_proto: str):
    """Solves the shift scheduling problem."""
    num_employees = len(employees)
    num_shifts = len(shifts)
    first_day_index = week.index(month_first_day)

    model = cp_model.CpModel()

    if not validate_input():
        return
########################################################################
# Basic Rules
########################################################################

    work = {}
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                work[e, s, d] = model.new_bool_var(f"work{e}_{s}_{d}")

    # Exactly one shift per 2 days
    for e in range(num_employees):
        for d in range(month_days - 1):
            model.add_at_most_one(work[e, s, d_] for d_ in [d, d+1] for s in range(num_shifts))

    #exclude shifts based to capability
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                if shifts[s] not in levels[employees[e][1]]:
                    model.add(work[e, s, d] == 0)

    #force all shifts to be covered
    total_shifts = 0
    for d in range(month_days):
            if is_holiday(d):
                day_shifts = set(holiday_shifts)
            else:
                day_shifts = set(week_day_shifts)
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


    print("avg shifts: " + str(avg_shifts) + " " + str(rem_shifts))
    print("total shifts " + str(total_shifts))

    # Objective
    model.minimize(
        1 # sum(cost for cost in costs)
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
        print_solution(solver, status, work)
    else:
        print("NOT SOLVED :-(")

def main(_):
    solve_shift_scheduling(_PARAMS.value, _OUTPUT_PROTO.value)


if __name__ == "__main__":
    app.run(main)
