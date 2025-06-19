#!/usr/bin/env python3
from operator import truediv

import pandas
from absl import app
from absl import flags
import os, tempfile
import webbrowser

from google.protobuf import text_format
from ortools.sat.python import cp_model
from pandas.compat.numpy.function import validate_sum
from pandas.core.array_algos.transforms import shift

_OUTPUT_PROTO = flags.DEFINE_string(
    "output_proto", "", "Output file to write the cp_model proto to."
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
    "AA": ["M1", "M2", "A1", "A2", "A3", "N1", "N2"],
    "A": ["M1", "M2", "A1", "A2", "A3", "N1", "N2", "IM", "IA"],
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
month_first_day = "Tu"
month_days = 31
public_holidays = []
prev_month_last_is_holiday = False
next_month_first_is_holiday = False
month_starts_with_internal = 0
hot_periods = []
filename = 'july.csv'

#end options
################################################################################

employees = []

employees_stats = []

class EmployeeStat:
    def __init__(self):
        self.shifts_count = None
        self.nights_count = None
        self.holidays_count = None
        self.more_than_five = None
        self.more_than_four = None
        self.more_than_three = None
        self.more_than_one_night = None
        self.two_nights_on_four = None
        self.one_night_on_three = None
        self.works_at_day = {}
        self.count_vars = {}

    def __str__(self):
        return f'more_than_three {self.more_than_three}, more_than_five {self.more_than_five},  two_nights {self.two_nights}, two_nights_on_four {self.two_nights_on_four}'

def is_holiday(d):
    if d == -1:
        return prev_month_last_is_holiday
    if d == month_days:
        return next_month_first_is_holiday

    first_day_index = week.index(month_first_day)
    if d + 1 in public_holidays:
        return True
    elif (d + first_day_index) % len(week) in [week.index("Sa"), week.index("Su")]:
        return True
    return False

def is_internal(s):
    return shifts[s] in ['IM', 'IA']

def is_external(s):
    return shifts[s] not in ['IM', 'IA']

def is_sunday(d):
    first_day_index = week.index(month_first_day)
    return (d + first_day_index) % len(week)  == week.index("Su")

def is_saturday(d):
    first_day_index = week.index(month_first_day)
    return (d + first_day_index) % len(week)  == week.index("Sa")

def is_other_holiday(d):
    return is_holiday(d) and not is_saturday(d) and not is_sunday(d)

def is_public_holiday(d):
    if d + 1 in public_holidays:
        return True
    return False

def get_night_shifts():
    return [shifts.index(x) for x in day_parts[2]]

def get_employee_name(e):
    return employees[e][0]

def get_employee_level(e):
    return employees[e][1]

def get_employee_extra_nights(e):
    return employees[e][3]

def get_employee_virtual_shifts(e):
    return employees[e][4]

def get_employee_capable_shifts(e):
    return levels[employees[e][1]]

def get_employee_min_shifts(e):
    return employees[e][2][0]

def get_employee_max_shifts(e):
    return employees[e][2][1]

def get_employee_preference(e,d,i):
    return employees[e][5][d][i]

def prefered_nights(e):
    count = 0
    for d in range(month_days):
        if get_employee_preference(e,d,2) == "P" or get_employee_preference(e,d,2) == "WP":
            if get_employee_preference(e,d,1) != "P" and get_employee_preference(e,d,1) != "WP":
                if get_employee_preference(e, d, 0) != "P" and get_employee_preference(e, d, 0) != "WP":
                    count += 1
    return count

def get_pos_prefs(e):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(e,d,i) == "WP":
                count += 1
    return count

def get_neg_prefs(e):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(e,d,i) == "WN":
                count += 1
    return count

def get_neg(e):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(e,d,i) == "N":
                count += 1
    return count

def get_pos(e):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(e,d,i) == "P":
                count += 1
    return count

def prefers_nights(e):
    return prefered_nights(e) > 10

def is_night_dp_idx(idx):
    return idx == 2

def is_night_shift(s):
    return shifts[s] in day_parts[2]

def get_day_part_shifts(part_idx):
    return [i for i in range(len(shifts)) if shifts[i] in day_parts[part_idx]]

def can_do_internal(e):
    e_shifts = levels[get_employee_level(e)]
    for shift in e_shifts:
        if is_internal(shifts.index(shift)):
            return True
    return False

def can_do_external(e):
    e_shifts = levels[get_employee_level(e)]
    for shift in e_shifts:
        if is_external(shifts.index(shift)):
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
        if len(e[5]) != month_days:
            valid = False
            print("invalid shift num pref days")
        for day_pref in e[5]:
            if len(day_pref)!=3:
                valid = False
                print("invalid shift num pref days len")
            for prf in day_pref:
                if prf not in ["I", "WP", "P", "WN", "N"]:
                    valid = False
                    print ("wrong pref str")

    return valid

def format_input(data):
    global employees
    employees = []

    for row in data:
        out = []
        out.append(row[0])
        out.append(row[1])
        out.append([int(row[2]), int(row[3])])
        out.append(row[4])
        out.append(row[5])
        prefs = []
        count = 0
        for i in range(6, len(row), 3):
            count += 1
            prefs.append([row[i],row[i+1],row[i+2]])
        out.append(prefs)
        employees.append(out)
        employees_stats.append(EmployeeStat())

        if month_days != count:
            print("wrong pref data")
            employees = []
            return None

def as_html_table(lines):
    out = r"<table>"

    for line in lines:
        out += '\n' + r'<tr>' + '\n  '
        for row in line:
            out += r'<td>' + str(row) + r'</td>'
        out += '\n' + r'</tr>'
    out += "\n" + r"</table>"
    return out

def html_bold(s):
    return r'<b>' + str(s) + r'</b>'

def html_bold_if(s, cond):
    if cond:
        return html_bold(s)
    else:
        return s

def html_mark(s):
    return r'<mark>' + str(s) + r'</mark>'

def html_mark_if(s, cond):
    if cond:
        return html_mark(s)
    else:
        return s

def in_brackets_if(s, cond):
    if cond:
        return '[' + s + ']'
    else:
        return s

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
        line.append(html_bold_if(str(d + 1), is_holiday(d)))
        line.append(html_bold_if(week[(d + first_day_index) % 7],is_holiday(d)))
        for s in range(num_shifts):
            shift_given = False
            for e in range(num_employees):
                if solver.boolean_value(work[e, s, d]):
                    line.append(html_bold_if(get_employee_name(e), is_holiday(d)))
                    shift_given = True
            if not shift_given:
                line.append("")
        output.append(line)
    # print(tabulate(output, tablefmt="html"))

    out2 = []
    header2 = ["NAME", "SHIFTS", "NIGHTS", "INTERN","HOLIDAYS", "Sa", "Su", "othr_ho", "days"]
    out2.append(header2)
    for e in range(num_employees):
        line = []
        sft = 0
        nght = 0
        intern = 0
        hdy = 0
        su = 0
        sa = 0
        oh = 0
        days = []
        line.append(f"{get_employee_name(e)} - {get_employee_level(e)}[{get_employee_min_shifts(e)},{get_employee_max_shifts(e)}][{get_employee_level(e)}]")
        for d in range(month_days):
            for s in range(num_shifts):
                if solver.boolean_value(work[e, s, d]):
                    #days.append(in_brackets_if( html_bold_if(str(d+1),is_holiday(d)), is_night_shift(s)))
                    days.append(html_bold_if(in_brackets_if(str(d+1),is_night_shift(s)),is_holiday(d)))
                    sft += 1
                    if is_holiday(d):
                        hdy +=1
                    if is_saturday(d):
                        sa += 1
                    if is_sunday(d):
                        su += 1
                    if is_other_holiday(d):
                        oh += 1
                    if s in get_night_shifts():
                        nght += 1
                    if is_internal(s):
                        intern += 1
        line.append(sft)
        line.append(nght)
        line.append(intern)
        line.append(hdy)
        line.append(sa)
        line.append(su)
        line.append(oh)
        line.append(','.join(days))

        out2.append(line)

    tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html')
    try:
        print(tmp.name)
        tmp.write(html_header)
        tmp.write(as_html_table(output))
        tmp.write('<br><br>')
        tmp.write(as_html_table(out2))
        tmp.write(html_footer)
    finally:
        tmp.close()
        webbrowser.open('file://' + os.path.realpath(tmp.name))

def can_do_nights(e):
    for x in day_parts[2]:
        if x in get_employee_capable_shifts(e):
            return True
    return False


def solve_shift_scheduling(output_proto: str):
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
    black_listed = {}
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                work[e, s, d] = model.new_bool_var(f"work{e}_{s}_{d}")
                black_listed[e, s, d] = False

    #employee works at d -  max one shift per day
    for e in range(num_employees):
        for d in range(month_days):
            day_shifts = [work[e, s, d] for s in range(num_shifts)]
            employees_stats[e].works_at_day[d] = model.new_bool_var(f"e_{e}_works_at_{d}")
            day_shifts.append(~employees_stats[e].works_at_day[d])
            model.add_exactly_one(day_shifts)

    # limit the cost of shifts
    for e in range(num_employees):
        weights = []
        costs = []
        max_cost = 77 - 10 * get_employee_virtual_shifts(e)
        for d in range(month_days):
            if is_sunday(d) or is_public_holiday(d):
                day_cost = 14
            elif is_saturday(d):
                day_cost = 12
            else:
                day_cost = 10
            for s in range(num_shifts):
                weights.append(work[e, s, d])
                costs.append(day_cost)
        weighted_sum = sum(weights[i] * costs[i] for i in range(len(costs)))
        model.Add(weighted_sum <= max_cost)

    #not close shifts
    for e in range(num_employees):
        penalties = [2000, 50, 45, 40, 35, 10, 5, 4]
        for index, value in enumerate(penalties):
            for d in range(month_days - index - 1):
                close_work_var = model.NewBoolVar(f'close_work_{e}_{d}_{index}')
                work_list = [employees_stats[e].works_at_day[d], employees_stats[e].works_at_day[d + index  + 1]]
                reverse_work_list = [~employees_stats[e].works_at_day[d], ~employees_stats[e].works_at_day[d + index + 1]]
                for i in range(d+1, d + index + 1):
                    work_list.append(~employees_stats[e].works_at_day[i])
                    reverse_work_list.append(employees_stats[e].works_at_day[i])

                model.AddBoolAnd(work_list).OnlyEnforceIf(close_work_var)
                model.AddBoolOr(reverse_work_list).OnlyEnforceIf(~close_work_var)
                cost_literals.append(close_work_var)
                cost_coefficients.append(value)

    #not close nights <= check this if it can be relaxed
    close_range = 2
    for e in range(num_employees):
        for d in range(month_days - close_range):
            model.add_at_most_one(work[e, s, d_] for d_ in range(d, d + close_range + 1) for s in get_night_shifts())

    #exclude shifts based to employee capability
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                if shifts[s] not in get_employee_capable_shifts(e):
                    model.add(work[e, s, d] == False)
                    black_listed[e, s, d] = True

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
                    model.add_exactly_one(works)
                    total_shifts += 1
                else:
                    for e in range(num_employees):
                        model.add(work[e, s, d] == False)
                        black_listed[e, s, d] = True

    night_input = {
        "prefix" : "night",
        "applicable": lambda e: can_do_nights(e) and get_employee_max_shifts(e) > 0,
        "lambda": lambda e, s, d: is_night_shift(s),
        "index" : lambda e: get_employee_extra_nights(e),
        "limits" : [
            {
                0: ((0, 0, 0), (0, 0, 0)),
                1: ((0, 0, 0), (0, 1, 1400)),
                2: ((0, 0, 0), (0, 1, 1400)),
                3: ((0, 0 ,0), (0, 1, 800)),
                4: ((0, 0, 0), (1, 2, 800)),
                5: ((0, 0, 0), (2, 3, 800)),
                6: ((0, 0, 0), (2, 3, 800)),
                7: ((0, 0, 0), (3, 3, 800)),
            },

            {
                0: ((0, 0, 0), (0, 0, 0)),
                1: ((0, 0, 0), (0, 1, 800)),
                2: ((0, 0, 0), (1, 1, 800)),
                3: ((0, 0, 0), (1, 1, 800)),
                4: ((0, 0, 0), (2, 2, 800)),
                5: ((0, 0, 0), (3, 3, 800)),
                6: ((0, 0, 0), (3, 3, 800)),
                7: ((0, 0, 0), (3, 3, 800)),
            },

            {
                0: ((0, 0, 0), (0, 0, 0)),
                1: ((0, 0, 0), (1, 1, 800)),
                2: ((0, 0, 0), (2, 2, 800)),
                3: ((0, 0, 0), (3, 3, 800)),
                4: ((0, 0, 0), (4, 4, 800)),
                5: ((0, 0, 0), (5, 5, 800)),
                6: ((0, 0, 0), (5, 5, 800)),
                7: ((0, 0, 0), (5, 5, 800)),
            },
        ]
    }

    add_constraints(model, work, night_input, num_employees, num_shifts, cost_coefficients, cost_literals)
                
    holiday_input = {
        "prefix" : "holiday",
        "applicable": lambda e: get_employee_max_shifts(e) > 0,
        "lambda": lambda e, s, d: is_holiday(d),
        "index" : lambda e:  0,
        "limits" : [
            {
                0: ((0, 0, 0), (0, 0, 0)),
                1: ((0, 0, 0), (1, 1, 300)),
                2: ((0, 0, 0), (1, 2, 300)),
                3: ((0, 0 ,0), (2, 3, 300)),
                4: ((0, 0, 0), (2, 4, 300)),
                5: ((0, 0, 0), (3, 5, 300)),
                6: ((0, 0, 0), (3, 5, 300)),
                7: ((0, 0, 0), (4, 5, 300)),
            },
        ]
    }

    add_constraints(model, work, holiday_input, num_employees, num_shifts, cost_coefficients, cost_literals)

    internal_input = {
        "prefix" : "internal",
        "applicable": lambda e: get_employee_max_shifts(e) > 0 and can_do_internal(e) and can_do_external(e),
        "lambda": lambda e, s, d: is_internal(s),
        "index" : lambda e:  1 if get_employee_level(e) == "D" else 0,
        "limits" : [
            {
                0: ((0, 0, 0), (0, 0, 0)),
                1: ((0, 0, 0), (1, 1, 200)),
                2: ((0, 0, 0), (2, 2, 200)),
                3: ((0, 0 ,0), (2, 3, 200)),
                4: ((0, 0, 0), (2, 4, 200)),
                5: ((0, 0, 0), (3, 5, 200)),
                6: ((0, 0, 0), (4, 6, 200)),
                7: ((0, 0, 0), (5, 7, 200)),
            },

            {
                0: ((0, 0, 0), (0, 0, 0)),
                1: ((0, 0, 0), (1, 1, 200)),
                2: ((0, 1, 200), (2, 2, 200)),
                3: ((1, 2, 200), (3, 3, 200)),
                4: ((1, 3, 200), (4, 4, 200)),
                5: ((1, 3, 200), (4, 5, 200)),
                6: ((0, 0, 0), (5, 6, 200)),
                7: ((0, 0, 0), (6, 7, 200)),
            },
        ]
    }

    add_constraints(model, work, internal_input, num_employees, num_shifts, cost_coefficients, cost_literals)

    #positives - negatives
    for e in range(num_employees):
        pos_prefs = get_pos_prefs(e)
        neg_prefs = get_neg_prefs(e)
        negs = get_neg(e)
        pos = get_pos(e)

        for d in range(month_days):
            for dp_idx in range(len(day_parts)):
                employee_works = [work[e, s, d] for s in get_day_part_shifts(dp_idx)]

                slot_pref = get_employee_preference(e, d, dp_idx)

                if slot_pref == "P":
                    model.add_exactly_one(employee_works)
                    can_do = False
                    for s in get_day_part_shifts(dp_idx):
                        if black_listed[e, s, d] == False:
                            can_do = True
                    if not can_do:
                        print(f'CAN DO ERROR {e} {s} {d}')


                if slot_pref == "N":
                    for w in employee_works:
                        model.add(w == 0)

                if slot_pref == "WN" or slot_pref == "WP":
                    name = f"worked_{e}_{d}_{dp_idx}"
                    worked = model.new_bool_var(name)
                    employee_works.append(~worked)
                    model.add_exactly_one(employee_works)
                    cost_literals.append(worked)

                    avail_days = (3*month_days - neg_prefs - negs - pos_prefs - pos) //3
                    weight = avail_days // 2
                    if weight <= 0:
                        weight = 1
                    if slot_pref == "WN":
                        cost_coefficients.append(weight)
                    else:
                        if is_night_dp_idx(dp_idx) and prefers_nights(e):
                            weight *= 3
                        cost_coefficients.append(-weight)


    #hot periods
    for e in range(num_employees):
        e_hot_periods=[]
        for h in range(len(hot_periods)):
            hot_works=[]
            for d1 in hot_periods[h]:
                d = d1 - 1
                for s in range(num_shifts):
                    hot_works.append(work[e, s, d])
            hot_work_var = model.new_bool_var(f"hot_work_e_{e}_h_{h}")
            model.add(sum(hot_works) > 0).only_enforce_if(hot_work_var)
            model.add(sum(hot_works) == 0).only_enforce_if(~hot_work_var)
            e_hot_periods.append(hot_work_var)
        model.add_at_most_one(e_hot_periods)


    avg_shifts = total_shifts // len(employees)
    rem_shifts = total_shifts % len(employees)


    print("avg shifts: " + str(avg_shifts) + " " + str(rem_shifts))
    print("total shifts " + str(total_shifts))

    # Objective
    model.minimize(
        #sum(cost_literals[i] * cost_coefficients[i] for i in range(len(cost_literals)))
        cp_model.LinearExpr.weighted_sum(cost_literals, cost_coefficients)
        #+
        #sum(obj_int_vars[i] * obj_int_coeffs[i] for i in range(len(obj_int_vars)))
    )

    if output_proto:
        print(f"Writing proto to {output_proto}")
        with open(output_proto, "w") as text_file:
            text_file.write(str(model))

    # Solve the model.
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    #solver.parameters.log_search_progress = True
    #solver.parameters.enumerate_all_solutions = True
    #solver.parameters.num_search_workers = 8
    #solver.parameters.log_to_stdout = True
    #solver.parameters.linearization_level = 0
    #solver.parameters.cp_model_presolve = True
    #solver.parameters.cp_model_probing_level = 0

    solution_printer = cp_model.ObjectiveSolutionPrinter()
    status = solver.solve(model, solution_printer)

    print("Status = %s" % solver.status_name(status))

    print("Statistics")
    print("  - conflicts : %i" % solver.num_conflicts)
    print("  - branches  : %i" % solver.num_branches)
    print("  - wall time : %f s" % solver.wall_time)
    print("  - number of solutions found: %i" % solution_printer.solution_count())

    # Print solution.
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("SOLVED")
        print_solution(solver, status, work)
    else:
        print("NOT SOLVED :-(")

    if status == cp_model.INFEASIBLE:
        # print infeasible boolean variables index
        print('SufficientAssumptionsForInfeasibility = 'f'{solver.SufficientAssumptionsForInfeasibility()}')

        # print infeasible boolean variables
        infeasibles = solver.SufficientAssumptionsForInfeasibility()
        for i in infeasibles:
            print('Infeasible constraint: %d' % model.GetBoolVarFromProtoIndex(i))


def add_constraints(model, work, specific_input, num_employees, num_shifts, cost_coefficients, cost_literals):
    for e in range(num_employees):
        total_var_name = f'new_total_count_{e}'
        if not total_var_name in employees_stats[e].count_vars:
            employees_stats[e].count_vars[total_var_name] = model.new_int_var(get_employee_min_shifts(e),
                                                                              get_employee_max_shifts(e),
                                                                              total_var_name)
            employee_works = [work[e, s, d] for s in range(num_shifts) for d in range(month_days)]
            model.add(employees_stats[e].count_vars[total_var_name] == sum(employee_works))

            for shift_count in range(get_employee_min_shifts(e), get_employee_max_shifts(e) + 1):
                count_var_name = f'{total_var_name}_{shift_count}'
                employees_stats[e].count_vars[count_var_name] = model.new_bool_var(count_var_name)
                model.add(employees_stats[e].count_vars[total_var_name] == shift_count).only_enforce_if(
                    employees_stats[e].count_vars[count_var_name])
                model.add(employees_stats[e].count_vars[total_var_name] != shift_count).only_enforce_if(
                    ~employees_stats[e].count_vars[count_var_name])

        if specific_input["applicable"](e):
            specific_var_name = f'new_{specific_input["prefix"]}_count_{e}'
            employees_stats[e].count_vars[specific_var_name] = model.new_int_var(0, get_employee_max_shifts(e),
                                                                                 specific_var_name)
            specific_employee_works = [work[e, s, d] for s in range(num_shifts) for d in range(month_days) if
                                       specific_input["lambda"](e, s, d)]
            model.add(employees_stats[e].count_vars[specific_var_name] == sum(specific_employee_works))

            for shift_count in range(get_employee_min_shifts(e), get_employee_max_shifts(e) + 1):
                soft_lim, hard_lim, penalty = specific_input["limits"][specific_input["index"](e)][shift_count][1]

                soft_var_name = f'new_{specific_input["prefix"]}_{e}_greater_than_{soft_lim}'
                hard_var_name = f'new_{specific_input["prefix"]}_{e}_greater_than_{hard_lim}'

                if soft_var_name not in employees_stats[e].count_vars:
                    employees_stats[e].count_vars[soft_var_name] = model.new_bool_var(soft_var_name)
                    model.add(employees_stats[e].count_vars[specific_var_name] > soft_lim).only_enforce_if(
                        employees_stats[e].count_vars[soft_var_name])
                    model.add(employees_stats[e].count_vars[specific_var_name] <= soft_lim).only_enforce_if(
                        ~employees_stats[e].count_vars[soft_var_name])

                if hard_var_name not in employees_stats[e].count_vars:
                    employees_stats[e].count_vars[hard_var_name] = model.new_bool_var(hard_var_name)
                    model.add(employees_stats[e].count_vars[specific_var_name] > hard_lim).only_enforce_if(
                        employees_stats[e].count_vars[hard_var_name])
                    model.add(employees_stats[e].count_vars[specific_var_name] <= hard_lim).only_enforce_if(
                        ~employees_stats[e].count_vars[hard_var_name])

                if shift_count > hard_lim:
                    model.add_bool_or(~employees_stats[e].count_vars[f'{total_var_name}_{shift_count}'],
                                  ~employees_stats[e].count_vars[hard_var_name])

                if hard_lim > soft_lim and shift_count > soft_lim:
                    soft_lim_var = f'{soft_var_name}_on_{shift_count}'
                    employees_stats[e].count_vars[soft_lim_var] = model.new_bool_var(soft_lim_var)
                    model.add_bool_or(~employees_stats[e].count_vars[f'{total_var_name}_{shift_count}'],
                                      ~employees_stats[e].count_vars[soft_var_name],
                                      employees_stats[e].count_vars[soft_lim_var])
                    cost_literals.append(employees_stats[e].count_vars[soft_lim_var])
                    cost_coefficients.append(penalty)

                #===================================================================================================
                soft_lim, hard_lim, penalty = specific_input["limits"][specific_input["index"](e)][shift_count][0]

                soft_var_name = f'new_{specific_input["prefix"]}_{e}_lower_than_{soft_lim}'
                hard_var_name = f'new_{specific_input["prefix"]}_{e}_lower_than_{hard_lim}'

                if soft_var_name not in employees_stats[e].count_vars:
                    employees_stats[e].count_vars[soft_var_name] = model.new_bool_var(soft_var_name)
                    model.add(employees_stats[e].count_vars[specific_var_name] < soft_lim).only_enforce_if(
                        employees_stats[e].count_vars[soft_var_name])
                    model.add(employees_stats[e].count_vars[specific_var_name] >= soft_lim).only_enforce_if(
                        ~employees_stats[e].count_vars[soft_var_name])

                if hard_var_name not in employees_stats[e].count_vars:
                    employees_stats[e].count_vars[hard_var_name] = model.new_bool_var(hard_var_name)
                    model.add(employees_stats[e].count_vars[specific_var_name] < hard_lim).only_enforce_if(
                        employees_stats[e].count_vars[hard_var_name])
                    model.add(employees_stats[e].count_vars[specific_var_name] >= hard_lim).only_enforce_if(
                        ~employees_stats[e].count_vars[hard_var_name])

                if hard_lim > 0:
                    model.add_bool_or(~employees_stats[e].count_vars[f'{total_var_name}_{shift_count}'],
                                  ~employees_stats[e].count_vars[hard_var_name])

                if soft_lim > 0 and soft_lim > hard_lim:
                    soft_lim_var = f'{soft_var_name}_on_{shift_count}'
                    employees_stats[e].count_vars[soft_lim_var] = model.new_bool_var(soft_lim_var)
                    model.add_bool_or(~employees_stats[e].count_vars[f'{total_var_name}_{shift_count}'],
                                      ~employees_stats[e].count_vars[soft_var_name],
                                      employees_stats[e].count_vars[soft_lim_var])
                    cost_literals.append(employees_stats[e].count_vars[soft_lim_var])
                    cost_coefficients.append(penalty)


def main(_):
    data = pandas.read_csv(filename).fillna("I")


    # Display the modified DataFrame
    #print(data.head())
    list_data = data.values.tolist()
    format_input(list_data)

    for e in employees:
        print(e)
    solve_shift_scheduling(_OUTPUT_PROTO.value)


if __name__ == "__main__":
    app.run(main)
