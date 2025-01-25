#!/usr/bin/env python3
import pandas
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
    "params", "max_time_in_seconds:20.0", "Sat solver parameters."
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
shifts = ["IM", "M1", "M2", "IA", "A1", "A2", "A3", "N1", "N2"]

shift_groups = [
    ["M1", "M2", "A1", "A2", "A3", "N1", "N2"],
    ["IM", "IA"]
]

week_day_shifts = ["IA", "A1", "A2", "A3", "N1", "N2"]
holiday_shifts = ["IM", "M1", "M2", "IA", "A1", "A2", "A3","N1", "N2"]

levels = {
    "A": ["M1", "A1", "N1", "A2"],
    "B": ["M2", "A2", "A3", "N2", "IM", "IA"],
    "C": ["M2", "A3", "N2", "IM", "IA"],
    "D": ["M2", "A3", "IM", "IA"],
    "E": ["M2", "A3"]
}

day_parts = [
    ["IM", "M1", "M2"],
    ["IA", "A1", "A2", "A3"],
    ["N1", "N2"]
]

shift_categories = {

}

# Data
################################################################################
#start options
month_first_day = "Sa"
month_days = 28
public_holidays = []
prev_month_last_is_holiday = False
next_month_first_is_holiday = False
month_starts_with_internal = 0

employees = []

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
    # for _, l, _, neg in employees:
    #     if not l in levels:
    #         print("wrong level " + l)
    #         valid = False
    #     for n in neg:
    #         if n > month_days or n < 1:
    #             print("wrong negative")
    #             valid = False
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

    for dp in day_parts:
        for s in dp:
            if not s in shifts:
                print("wrong day part")
                valid = False

    for s in shifts:
        c = 0
        for dp in day_parts:
            for sdp in dp:
                if s == sdp:
                    c += 1
        if c != 1:
            print("wrong day part2" + str(c))
            valid = False

    for e in employees:
        if e[1] not in levels:
            valid = False
            print ("not in levels")
        if len(e[2]) != 2:
            valid = False
            print("invalid shift num pref")
        if len(e[3]) != month_days:
            valid = False
            print("invalid shift num pref days")
        for day_pref in e[3]:
            if len(day_pref)!=3:
                valid = False
                print("invalid shift num pref days len")
            for prf in day_pref:
                if prf not in ["I", "WP", "P", "WN", "N"]:
                    valid = False
                    print ("wrong pref str")

    return valid

def format_input(data):
    for row in data:
        out = []
        out.append(row[0])
        out.append(row[1])
        out.append([int(row[2]), int(row[3])])
        prefs = []
        for i in range(4, len(row), 3):
            prefs.append([row[i],row[i+1],row[i+2]])
        out.append(prefs)
        employees.append(out)


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


def negated_bounded_span(works, e, s1, s2, d, length):

    sequence = []
    # left border (start of works, or works[start - 1])
    if d > 0:
        sequence.append(works[e,s1, d - 1])
    for i in range(length):
        for si in range(len(shifts)):
            sequence.append(~works[e,si,d + i])
    # right border (end of works or works[start + length])
    if d + length < month_days:
        sequence.append(works[e,s2,d + length])
    return sequence



def negated_bounded_span2(works, e, s1, s2, start, end):
    sequence = []
    # left border (start of works, or works[start - 1])
    sequence.append(works[e,s1, start])
    sequence.append(works[e, s2, end])
    for i in range(length):
        sequence.append(~works[start + i])

    return sequence


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
    cost_literals = []
    cost_coefficients = []

    work = {}
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                work[e, s, d] = model.new_bool_var(f"work{e}_{s}_{d}")

    # Exactly one shift per 2 days
    for e in range(num_employees):
        for d in range(month_days - 1):
            model.add_at_most_one(work[e, s, d_] for d_ in [d, d+1] for s in range(num_shifts))

    #exclude shifts based to employee capability
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
            day_shifts = day_shifts.intersection(set(shift_groups[(d + month_starts_with_internal) % len(shift_groups)]))

            for s in range(num_shifts):
                works = [work[e, s, d] for e in range(num_employees)]
                if shifts[s] in day_shifts:
                    model.add(1 == sum(works))
                    total_shifts += 1
                else:
                    model.add(0 == sum(works))

    #shifts num per employee
    for e in range(num_employees):
        name = f"shifts_count({e})"

        if employees[e][2][0] > 3:
            employees[e][2][0] = 3

        shifts_count = model.new_int_var(employees[e][2][0], employees[e][2][1], name)
        employee_works = [work[e, s, d] for s in range(num_shifts) for d in range(month_days)]
        model.add(shifts_count == sum(employee_works))

    ##positives - negatives
    for e in range(num_employees):
        for d in range(month_days):
            day_parts_idx = -1
            for dp in day_parts:
                day_parts_idx += 1
                part_shifts = []
                for s1 in range(num_shifts):
                    if shifts[s1] in dp:
                        part_shifts.append(s1)
                employee_works = [work[e, s, d] for s in part_shifts]

                if employees[e][3][d][day_parts_idx] == "P":
                    model.add(1 == sum(employee_works))

                if employees[e][3][d][day_parts_idx] == "N":
                    model.add(0 == sum(employee_works))

                if employees[e][3][d][day_parts_idx] == "NP":
                    name = f"np_{e}_{d}_dp_{day_parts_idx}"
                    np = model.new_bool_var(name)
                    employee_works.append(~np)
                    model.add_bool_or(employee_works)
                    cost_literals.append(np)
                    cost_coefficients.append(10)

                if employees[e][3][d][day_parts_idx] == "WP":
                    name = f"p_{e}_{d}_dp_{day_parts_idx}"
                    p = model.new_bool_var(name)
                    employee_works.append(p)
                    model.add_bool_or(employee_works)
                    cost_literals.append(p)
                    cost_coefficients.append(10)

    #shifts spread
    out_days = []
    for e in range(num_employees):
        row = []
        for d in range(month_days):
            on_duty = [work[e, s, d] for s in range(num_shifts)]
            name = f"out_e_{e}_d_{d}"
            out_day = model.new_bool_var(name)
            on_duty.append(out_day)
            model.add_bool_or(on_duty)
            row.append(out_day)
        out_days.append(row)

    window_size = 12
    shifts_on_window = 3
    for e in range(num_employees):
        for d in range(month_days - window_size):
            shifts_count = model.new_int_var(0, shifts_on_window, f"window_e_{e}_d_{d}")
            works = [work[e, s, d1] for d1 in range(d, d +window_size) for s in range(num_shifts)]
            model.add(shifts_count == sum(works))

    window2_size = 5
    shifts_on_window2 = 2
    for e in range(num_employees):
        for d in range(month_days - window2_size):
            shifts_count = model.new_int_var(0, shifts_on_window2, f"window2_e_{e}_d_{d}")
            works = [work[e, s, d1] for d1 in range(d, d +window2_size) for s in range(num_shifts)]
            model.add(shifts_count == sum(works))

    # soft_min = 4
    # for e in range(num_employees):
    #     for d1 in range(month_days):
    #         for d2 in range(month_days):
    #             if d2> d1:
    #                 seq = []
    #                 if d1 > 0:
    #                     seq.append(out_days[e][d1-1])
    #                 if d2 < (month_days - 1):
    #                     seq.append(out_days[e][d2 + 1])
    #                 for i in range(d1, d2+1):
    #                     seq.append(~out_days[e][i])
    #                 name = f"out_e_{e}_d1_{d1}_d2_{d2}"
    #                 out_day = model.new_bool_var(name)
    #                 seq.append(out_day)
    #                 model.add_bool_or(seq)
    #                 cost_literals.append(out_day)
    #                 if d2-d1 > soft_min:
    #                     cost_coefficients.append(10 * soft_min)
    #                 else:
    #                     cost_coefficients.append(10 * (d2 - d1))


    avg_shifts = total_shifts // len(employees)
    rem_shifts = total_shifts % len(employees)


    print("avg shifts: " + str(avg_shifts) + " " + str(rem_shifts))
    print("total shifts " + str(total_shifts))

    # Objective
    model.minimize(
        sum(cost_literals[i] * cost_coefficients[i] for i in range(len(cost_literals)))
        #+
        #sum(obj_int_vars[i] * obj_int_coeffs[i] for i in range(len(obj_int_vars)))
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
    data = pandas.read_csv('data.csv')


    # Display the modified DataFrame
    #print(data.head())
    list_data = data.values.tolist()
    format_input(list_data)

    print(employees)
    solve_shift_scheduling(_PARAMS.value, _OUTPUT_PROTO.value)


if __name__ == "__main__":
    app.run(main)
