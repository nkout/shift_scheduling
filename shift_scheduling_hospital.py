#!/usr/bin/env python3
import shutil
from operator import truediv

import pandas
from absl import app
from absl import flags
import os, tempfile
import webbrowser
from config import *
from ortools.sat.python import cp_model

month_starts_with_internal = 1 if month_starts_with_internal_shift  else 0

# time budget (seconds) for each experimental re-solve during infeasibility diagnosis
diagnostic_solve_time = 10

# When RELAX_HARD is True, hard rules are turned into soft ones (a violation indicator
# with a big penalty) so an infeasible month still yields a best-effort schedule and we
# can report exactly which rules had to be broken. Reset per solve.
RELAX_HARD = False
RELAX_PENALTY = 100000
relaxations = []  # list of (bool_var, description) for softened hard-constraint violations

def register_violation(model, cost_literals, cost_coefficients, description, weight=RELAX_PENALTY):
    """Create a penalized 'this hard rule was broken' indicator and track it for reporting."""
    v = model.new_bool_var(f"violation_{len(relaxations)}")
    relaxations.append((v, description))
    cost_literals.append(v)
    cost_coefficients.append(weight)
    return v


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

class EmployeeStat:
    def __init__(self):
        self.works_at_day = {}
        self.count_vars = {}
        self.vars_weights = {}
    def add_var_weight(self, var, weight):
        if weight not in self.vars_weights:
            self.vars_weights[weight] = []
        self.vars_weights[weight].append(var)

    def print_weights(self, solver, thres):
        out = []
        for weight in self.vars_weights:
            for var in self.vars_weights[weight]:
                if solver.boolean_value(var):
                    out.append((str(var), weight))
        sorted_by_second = sorted(out, key=lambda tup: tup[1], reverse=True)
        str_out = []

        for srt in sorted_by_second:
            str_out.append(html_bold_if(f"{str(srt[0])}: {srt[1]}", srt[1] > thres ))
        return str_out

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

def day_part_name(dp_idx):
    return ["morning", "afternoon", "night"][dp_idx] if dp_idx < 3 else str(dp_idx)

def get_employee_name(employees, e):
    return employees[e][0]

def get_employee_level(employees, e):
    return employees[e][1]

def get_employee_extra_nights(employees, e):
    return employees[e][3]

def get_employee_virtual_shifts(employees,e):
    return employees[e][4]

def get_employee_gift_shifts(employees, e):
    return employees[e][5]

def get_employee_capable_shifts(employees, e):
    return levels[employees[e][1]]

def get_employee_min_shifts(employees, e):
    return employees[e][2][0]

def get_employee_max_shifts(employees, e):
    return employees[e][2][1]

def get_employee_preference(employees, e,d,i):
    return employees[e][6][d][i]

def get_prefs(employees, e, pref):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(employees,e,d,i) == pref:
                count += 1
    return count

def get_pos_prefs(employees, e):
    return get_prefs(employees, e, "WP")

def get_neg_prefs(employees, e):
    return get_prefs(employees, e, "WN")

def get_neg(employees, e):
    return get_prefs(employees, e, "N")

def get_pos(employees,e):
    return get_prefs(employees, e, "P")

def is_night_dp_idx(idx):
    return idx == 2

def is_night_shift(s):
    return shifts[s] in day_parts[2]

def get_day_part_shifts(part_idx):
    return [i for i in range(len(shifts)) if shifts[i] in day_parts[part_idx]]

def can_do_internal(employees,e):
    e_shifts = levels[get_employee_level(employees,e)]
    for shift in e_shifts:
        if is_internal(shifts.index(shift)):
            return True
    return False

def can_do_external(employees, e):
    e_shifts = levels[get_employee_level(employees,e)]
    for shift in e_shifts:
        if is_external(shifts.index(shift)):
            return True
    return False

def validate_input(employees):
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

    for pl in level_penalties:
        if pl not in levels:
            print("ivalid level penalty")
            valid = False
        for sft in level_penalties[pl]:
            if sft not in levels[pl]:
                print("ivalid level penalty shift")
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
            print (f"{e} not in levels")
        if len(e[2]) != 2:
            valid = False
            print("invalid shift num pref")
        if len(e[6]) != month_days:
            valid = False
            print("invalid shift num pref days")
        if e[5] > 0 and e[4] > 0:
            valid = False
            print("both virtual and gift shifts")
        for day_pref in e[6]:
            if len(day_pref)!=3:
                valid = False
                print("invalid shift num pref days len")
            for prf in day_pref:
                if prf not in ["I", "WP", "P", "WN", "N"]:
                    valid = False
                    print (f"wrong pref str {prf}")

    return valid

def format_input(data, employees, employees_stats):

    for row in data:
        out = []
        out.append(row[0])
        out.append(row[1])
        out.append([int(row[2]), int(row[3])])
        out.append(row[4])
        out.append(row[5])
        out.append(row[6])
        prefs = []
        count = 0
        for i in range(7, len(row), 3):
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

def print_solution(solver, status, work, virtual_work, employees, employees_stats):
    num_employees = len(employees)
    num_shifts = len(shifts)
    first_day_index = week.index(month_first_day)

    if status == cp_model.OPTIMAL:
        print("OPTIMAL")
    output = []
    header = ["", ""]
    header += shifts
    header.append("VIRTUAL")
    output.append(header)
    for d in range(month_days):
        line = []
        line.append(html_bold_if(str(d + 1), is_holiday(d)))
        line.append(html_bold_if(week[(d + first_day_index) % 7],is_holiday(d)))
        for s in range(num_shifts):
            shift_given = False
            for e in range(num_employees):
                if solver.boolean_value(work[e, s, d]):
                    line.append(html_bold_if(get_employee_name(employees,e), is_holiday(d)))
                    shift_given = True
            if not shift_given:
                line.append("")
        virtual_found = False
        for e in range(num_employees):
            if solver.boolean_value(virtual_work[e, d]):
                line.append(html_bold_if(get_employee_name(employees,e), is_holiday(d)))
                virtual_found = True
                break
        if not virtual_found:
            line.append("")
        output.append(line)
    # print(tabulate(output, tablefmt="html"))

    out2 = []
    header2 = ["NAME", "SHIFTS", "NIGHTS", "INTERN","HOLIDAYS", "SA", "SU", "OTHER_HOL", "VIRTUAL","DAYS", "PENALTIES"]
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
        virtual_w = 0

        gift_str = ""
        virtual_str = ""
        if get_employee_virtual_shifts(employees,e) > 0:
            virtual_str = f',V:{get_employee_virtual_shifts(employees,e)}'
        if get_employee_gift_shifts(employees,e) > 0:
            gift_str = f',P:{get_employee_gift_shifts(employees,e)}'
        formated_name = f"{get_employee_name(employees,e)} - {get_employee_level(employees,e)}[{get_employee_min_shifts(employees,e)},{get_employee_max_shifts(employees,e)}][{get_employee_level(employees,e)}{virtual_str}{gift_str}]"

        line.append(formated_name)
        for d in range(month_days):
            if solver.boolean_value(virtual_work[e, d]):
                virtual_w += 1
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
        line.append(html_bold_if(virtual_w, get_employee_virtual_shifts(employees,e) > 0))
        line.append(','.join(days))
        line.append(','.join(employees_stats[e].print_weights(solver, 80)))

        out2.append(line)

    out_logistics = []
    empty_shifts = [""] * 7
    out_logistics.append(["α/α", "ΒΑΘΜΟΣ", "ΟΝΟΜΑΤΕΠΩΝΥΜΟ"] + empty_shifts + ["ΑΡΙΘΜΟΣ ΕΦΗΜ."])
    for e in range(num_employees):
        line = [str(e+1), "", get_employee_name(employees,e)]
        empl_shifts = []
        for d in range(month_days):
            if solver.boolean_value(virtual_work[e, d]):
                empl_shifts.append(str(d+1))
            else:
                for s in range(num_shifts):
                    if solver.boolean_value(work[e, s, d]):
                        empl_shifts.append(str(d + 1))
        line += (empl_shifts + empty_shifts)[:7]
        has_gift = " +gift" if get_employee_gift_shifts(employees,e) > 0 else ""
        line.append(str(len(empl_shifts)) + has_gift)
        out_logistics.append(line)

    out_official = []
    out_official.append(["", "","", "ΠΡΩΙ", "", "ΑΠΟΓΕΥΜΑ", "", "",  "ΒΡΑΔΥ", ""])
    for d in range(month_days):
        line = []
        line.append(str(d + 1))
        line.append(week_gr[(d + first_day_index) % 7])
        if (d + month_starts_with_internal) % len(shift_groups) == 1:
            line.append("ΕΣ")
        else:
            line.append("EN")

        for day_part_i in range(len(day_parts)):
            day_part = day_parts[day_part_i]
            part_sifts = []
            for s in range(num_shifts):
                for e in range(num_employees):
                    if solver.boolean_value(work[e, s, d]) and shifts[s] in day_part:
                        part_sifts.append(get_employee_name(employees,e))
            if day_part_i == 2:
                for e in range(num_employees):
                    if solver.boolean_value(virtual_work[e, d]):
                        part_sifts.append(get_employee_name(employees,e))
            part_len = 3 if day_part_i == 1 else 2
            part_sifts = (part_sifts + empty_shifts)[:part_len]
            line +=part_sifts

        out_official.append(line)

    out_official2 = []
    for line in out_official[1:]:
        out_list = ([x for x in line if x != ""] + empty_shifts)[0:10]
        out_official2.append(out_list)

    tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html')
    try:
        print(tmp.name)
        tmp.write(html_header)
        tmp.write(as_html_table(output))
        tmp.write('<br><br>')
        tmp.write(as_html_table(out2))
        tmp.write('<br><br>')
        tmp.write(as_html_table(out_logistics))
        tmp.write('<br><br>')
        tmp.write(as_html_table(out_official))
        tmp.write('<br><br>')
        tmp.write(as_html_table(out_official2))
        tmp.write(html_footer)
    finally:
        tmp.close()
        if colab_execution:
            shutil.copyfile(os.path.realpath(tmp.name), os.path.join(os.path.realpath("."),"solution.html"))
        else:
            webbrowser.open('file://' + os.path.realpath(tmp.name))

def can_do_nights(employees,e):
    for x in day_parts[2]:
        if x in get_employee_capable_shifts(employees,e):
            return True
    return False

class MuteSolutionPrinter(cp_model.CpSolverSolutionCallback):
    """Print intermediate solutions."""

    def __init__(self):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self.__solution_count = 0

    def on_solution_callback(self) -> None:
        self.__solution_count += 1

    def solution_count(self) -> int:
        return self.__solution_count

def solve_shift_scheduling(output_proto: str, cost_literals, cost_coefficients, work, virtual_work, black_listed, employees, employees_stats, check_days, diagnostic=False):
    """Solves the shift scheduling problem."""
    num_employees = len(employees)
    num_shifts = len(shifts)
    first_day_index = week.index(month_first_day)

    model = cp_model.CpModel()
    relaxations.clear()

    if not validate_input(employees):
        return
########################################################################
# Basic Rules
########################################################################
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                work[e, s, d] = model.new_bool_var(f"work{e}_{s}_{d}")
                black_listed[e, s, d] = False

    for e in range(num_employees):
        for d in range(month_days):
            virtual_work[e,d] = model.new_bool_var(f"virtual_work{e}_{d}")

    #employee works at d -  max one shift per day
    for e in range(num_employees):
        for d in range(month_days):
            day_shifts = [work[e, s, d] for s in range(num_shifts)]
            employees_stats[e].works_at_day[d] = model.new_bool_var(f"e_{e}_works_at_{d}")
            day_shifts.append(~employees_stats[e].works_at_day[d])
            model.add_exactly_one(day_shifts)
            model.add_at_most_one([employees_stats[e].works_at_day[d], virtual_work[e,d]])

    # limit the cost of shifts
    for e in range(num_employees):
        weights = []
        costs = []
        max_cost = salaries["max"]  - 10 * get_employee_gift_shifts(employees,e)
        for d in range(month_days):
            if is_public_holiday(d):
                day_cost = salaries["holiday"]
            elif is_sunday(d):
                day_cost = salaries["Su"]
            elif is_saturday(d):
                day_cost = salaries["Sa"]
            else:
                day_cost = salaries["weekday"]
            for s in range(num_shifts):
                weights.append(work[e, s, d])
                costs.append(day_cost)
            weights.append(virtual_work[e, d])
            costs.append(day_cost)
        weighted_sum = sum(weights[i] * costs[i] for i in range(len(costs)))
        if RELAX_HARD:
            v = register_violation(model, cost_literals, cost_coefficients,
                                   f"{get_employee_name(employees,e)}: salary cap ({max_cost}) exceeded", 2 * RELAX_PENALTY)
            model.Add(weighted_sum <= max_cost).OnlyEnforceIf(~v)
        else:
            model.Add(weighted_sum <= max_cost)

    #not close shifts
    for e in range(num_employees):
        for index, value in enumerate(close_shift_penalties):
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
                employees_stats[e].add_var_weight(close_work_var, value)

    #not close nights <= check this if it can be relaxed
    for e in range(num_employees):
        for d in range(month_days - close_nights_range):
            close_count = f'close_nights_count_{e}_{d}'
            employees_stats[e].count_vars[close_count] = model.new_int_var(0, get_employee_max_shifts(employees,e),close_count)
            model.add(employees_stats[e].count_vars[close_count] == sum(work[e, s, d_] for d_ in range(d, d + close_nights_range + 1) for s in get_night_shifts()))
            close_var = f'close_nights_{e}_{d}'
            employees_stats[e].count_vars[close_var] = model.NewBoolVar(close_var)
            model.add(employees_stats[e].count_vars[close_count] > 1).only_enforce_if(
                employees_stats[e].count_vars[close_var])
            model.add(employees_stats[e].count_vars[close_count] <= 1).only_enforce_if(
                ~employees_stats[e].count_vars[close_var])
            cost_literals.append(employees_stats[e].count_vars[close_var])
            cost_coefficients.append(close_nights_penalty)
            employees_stats[e].add_var_weight(employees_stats[e].count_vars[close_var], close_nights_penalty)

    #exclude shifts based to employee capability
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                if shifts[s] not in get_employee_capable_shifts(employees,e):
                    model.add(work[e, s, d] == False)
                    black_listed[e, s, d] = True
                if get_employee_level(employees, e) in level_penalties:
                    if shifts[s] in level_penalties[get_employee_level(employees, e)]:
                        penalty_shift = model.NewBoolVar(f'penalty_shift_{e}_{s}_{d}')
                        model.add_exactly_one([penalty_shift, ~work[e, s, d]])
                        cost_literals.append(penalty_shift)
                        cost_coefficients.append(level_penalties[get_employee_level(employees, e)][shifts[s]])
                        employees_stats[e].add_var_weight(penalty_shift, level_penalties[get_employee_level(employees, e)][shifts[s]])

    #force all shifts to be covered
    total_shifts = 0
    for d in range(month_days):
        if len(check_days) > 0 and not d in check_days:
            continue

        if is_holiday(d):
            day_shifts = set(holiday_shifts)
        else:
            day_shifts = set(week_day_shifts)
        day_shifts = day_shifts.intersection(set(shift_groups[(d + month_starts_with_internal) % len(shift_groups)]))

        for s in range(num_shifts):
            works = [work[e, s, d] for e in range(num_employees)]
            if shifts[s] in day_shifts:
                if RELAX_HARD:
                    v = register_violation(model, cost_literals, cost_coefficients,
                                           f"shift {shifts[s]} on day {d+1} LEFT UNCOVERED", 5 * RELAX_PENALTY)
                    model.add_exactly_one(works + [v])
                else:
                    model.add_exactly_one(works)
                total_shifts += 1
            else:
                for e in range(num_employees):
                    model.add(work[e, s, d] == False)
                    black_listed[e, s, d] = True

    #force virtual shifts to be covered
    for d in range(month_days):
        if len(check_days) > 0 and not d in check_days:
            continue

        if (d + month_starts_with_internal) % len(shift_groups) == 1:
            vw = [virtual_work[e, d] for e in range(num_employees)]
            if RELAX_HARD:
                v = register_violation(model, cost_literals, cost_coefficients,
                                       f"virtual reserve on day {d+1} LEFT UNCOVERED", 5 * RELAX_PENALTY)
                model.add_exactly_one(vw + [v])
            else:
                model.add_exactly_one(vw)
        else:
            for e in range(num_employees):
                model.add(virtual_work[e, d] == False)

    night_input = {
        "prefix": "night",
        "applicable": lambda e: can_do_nights(employees, e) and get_employee_max_shifts(employees, e) > 0,
        "lambda": lambda e, s, d: is_night_shift(s),
        "index": lambda e: get_employee_extra_nights(employees, e),
        "limits": night_limits
    }

    holiday_input = {
        "prefix": "holiday",
        "applicable": lambda e: get_employee_max_shifts(employees, e) > 0,
        "lambda": lambda e, s, d: is_holiday(d),
        "index": lambda e: 0,
        "limits": holiday_limits
    }

    internal_input = {
        "prefix": "internal",
        "applicable": lambda e: get_employee_max_shifts(employees, e) > 0 and can_do_internal(employees,e) and can_do_external(employees, e),
        "lambda": lambda e, s, d: is_internal(s),
        "index": lambda e: 2 if get_employee_level(employees, e) == "D" else 1 if get_employee_level(employees,e) == "C" else 0,
        "limits": internal_limits
    }

    virtual_input = {
        "prefix": "virtual",
        "applicable": lambda ee: True,
        "set_lambda": lambda ee: [virtual_work[ee, dd] for dd in range(month_days)],
        "max_value": 2,
        "index": lambda ee: 1 if get_employee_virtual_shifts(employees, ee) > 0 else 0,
        "limits": virtual_limits,
        "total_lambda": lambda e, s, d: is_night_shift(s),
    }

    add_constraints(model, work, night_input, num_employees, num_shifts, cost_coefficients, cost_literals,employees, employees_stats)
    add_constraints(model, work, holiday_input, num_employees, num_shifts, cost_coefficients, cost_literals, employees, employees_stats)
    add_constraints(model, work, virtual_input, num_employees, num_shifts, cost_coefficients, cost_literals, employees, employees_stats)
    add_constraints(model, work, internal_input, num_employees, num_shifts, cost_coefficients, cost_literals, employees, employees_stats)
    
    for grp in exclusive_groups:
        if not diagnostic:
            print(f"exclusive group {[get_employee_name(employees,e) for e in grp]}")
        for d in range(month_days):
            for dp_idx in range(len(day_parts)):
                grp_works = []
                for s in get_day_part_shifts(dp_idx):
                    for e in grp:
                        grp_works.append(work[e, s, d])
                if RELAX_HARD:
                    grp_names = [get_employee_name(employees, e) for e in grp]
                    v = register_violation(model, cost_literals, cost_coefficients,
                                           f"exclusive group {grp_names} share day {d+1} {day_part_name(dp_idx)}")
                    model.add(sum(grp_works) <= 1).OnlyEnforceIf(~v)
                else:
                    model.add_at_most_one(grp_works)
                
    #positives - negatives
    for e in range(num_employees):
        pos_prefs = get_pos_prefs(employees,e)
        neg_prefs = get_neg_prefs(employees,e)
        negs = get_neg(employees,e)
        pos = get_pos(employees,e)

        for d in range(month_days):
            virtual_negative_added = False
            for dp_idx in range(len(day_parts)):
                employee_works = [work[e, s, d] for s in get_day_part_shifts(dp_idx)]
                slot_pref = get_employee_preference(employees,e, d, dp_idx)

                if slot_pref == "P":
                    if RELAX_HARD:
                        v = register_violation(model, cost_literals, cost_coefficients,
                                               f"{get_employee_name(employees,e)}: must-work (P) NOT honored, day {d+1} {day_part_name(dp_idx)}", 3 * RELAX_PENALTY)
                        model.add_exactly_one(employee_works + [v])
                    else:
                        model.add_exactly_one(employee_works)
                    can_do = False
                    for s in get_day_part_shifts(dp_idx):
                        if not black_listed[e, s, d]:
                            can_do = True
                    if not can_do:
                        print(f'CAN DO ERROR e {e} s {s} d {d}')

                if slot_pref == "N":
                    if RELAX_HARD:
                        v = register_violation(model, cost_literals, cost_coefficients,
                                               f"{get_employee_name(employees,e)}: must-not-work (N) VIOLATED, day {d+1} {day_part_name(dp_idx)}", 3 * RELAX_PENALTY)
                        for w in employee_works:
                            model.add(w == 0).OnlyEnforceIf(~v)
                        if not virtual_negative_added:
                            model.add(virtual_work[e, d] == False).OnlyEnforceIf(~v)
                            virtual_negative_added = True
                    else:
                        for w in employee_works:
                            model.add(w == 0)
                        if not virtual_negative_added:
                            model.add(virtual_work[e, d] == False)
                            virtual_negative_added = True

                if slot_pref == "WN" or slot_pref == "WP":
                    name = f"worked_pref_{e}_{d}_{dp_idx}"
                    worked = model.new_bool_var(name)


                    avail_slots = (3*month_days - negs - pos)
                    weight = int(round(pref_factor * (avail_slots - pos_prefs - neg_prefs) / (avail_slots + 1)))
                    if slot_pref == "WN":
                        employee_works.append(~worked)
                    else:
                        employee_works.append(worked)
                    model.add_exactly_one(employee_works)
                    cost_literals.append(worked)
                    cost_coefficients.append(weight)
                    employees_stats[e].add_var_weight(worked, weight)


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

    if len(check_days) == 0 and not diagnostic:
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

    with open("model.pbtxt", "w") as f:
        f.write(str(model.Proto()))

    # Solve the model.
    solver = cp_model.CpSolver()
    if diagnostic:
        solver.parameters.max_time_in_seconds = diagnostic_solve_time
    elif len(check_days) == 0:
        solver.parameters.max_time_in_seconds = max_solve_time
    else:
        solver.parameters.max_time_in_seconds = max_solve_time_check
    #solver.parameters.log_search_progress = True
    #solver.parameters.enumerate_all_solutions = True
    #solver.parameters.num_search_workers = 8
    #solver.parameters.log_to_stdout = True
    #solver.parameters.linearization_level = 0
    #solver.parameters.cp_model_presolve = True
    #solver.parameters.cp_model_probing_level = 0
    #
    # solver.parameters.log_search_progress = True
    # solver.parameters.cp_model_presolve = True
    # #solver.parameters.compute_intermediate_stats = True
    # solver.parameters.log_to_stdout = True
    #
    #
    # print(model.validate())

    #solver.parameters.log_to_stdout = True
    #model.Proto().ClearField("solution_hint")
    #print(model.Proto())

    solution_printer = cp_model.ObjectiveSolutionPrinter()  if (len(check_days) == 0 and not diagnostic) else MuteSolutionPrinter()
    status = solver.solve(model, solution_printer)

    if len(check_days) == 0 and not diagnostic:
        print("Status = %s" % solver.status_name(status))

        print("Statistics")
        print("  - conflicts : %i" % solver.num_conflicts)
        print("  - branches  : %i" % solver.num_branches)
        print("  - wall time : %f s" % solver.wall_time)
        print("  - number of solutions found: %i" % solution_printer.solution_count())

    # Print solution.
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        if RELAX_HARD and not diagnostic:
            print_broken_rules(solver)
        if len(check_days) == 0 and not diagnostic:
            print("SOLVED")
            print_solution(solver, status, work, virtual_work, employees, employees_stats)
        return True
    else:
        if not diagnostic:
            print("NOT SOLVED :-(")

            if status == cp_model.INFEASIBLE:
                # print infeasible boolean variables index
                print('SufficientAssumptionsForInfeasibility = 'f'{solver.SufficientAssumptionsForInfeasibility()}')

                # print infeasible boolean variables
                infeasibles = solver.SufficientAssumptionsForInfeasibility()
                for i in infeasibles:
                    print('Infeasible constraint: %d' % model.GetBoolVarFromProtoIndex(i))
        return False


def add_constraints(model, work, specific_input, num_employees, num_shifts, cost_coefficients, cost_literals, employees, employees_stats):
    for e in range(num_employees):
        # in RELAX_HARD mode the MIN floor becomes soft, so start the count domain at 0
        start_shifts = 0 if ("total_lambda" in specific_input or RELAX_HARD) else get_employee_min_shifts(employees,e)
        total_var_name = f'cnst_total_count_{e}' if "total_lambda" not in specific_input else f'cnst_total_count_{specific_input["prefix"]}_{e}'

        if total_var_name not in employees_stats[e].count_vars:
            employees_stats[e].count_vars[total_var_name] = model.new_int_var(start_shifts,
                                                                              get_employee_max_shifts(employees,e),
                                                                              total_var_name)
            employee_works = [work[e, s, d] for s in range(num_shifts) for d in range(month_days) if (("total_lambda" not in specific_input) or specific_input["total_lambda"](e, s, d))]
            #if "total_lambda" in specific_input:
            #    print (f'{total_var_name} = sum of {len(employee_works)} variables')
            model.add(employees_stats[e].count_vars[total_var_name] == sum(employee_works))

            if RELAX_HARD and "total_lambda" not in specific_input:
                real_min = get_employee_min_shifts(employees, e)
                if real_min > 0:
                    below = register_violation(model, cost_literals, cost_coefficients,
                        f"{get_employee_name(employees,e)}: total shifts below MIN {real_min}", 2 * RELAX_PENALTY)
                    model.add(employees_stats[e].count_vars[total_var_name] >= real_min).OnlyEnforceIf(~below)
                    model.add(employees_stats[e].count_vars[total_var_name] < real_min).OnlyEnforceIf(below)

            for shift_count in range(start_shifts, get_employee_max_shifts(employees,e) + 1):
                count_var_name = f'{total_var_name}_{shift_count}'
                employees_stats[e].count_vars[count_var_name] = model.new_bool_var(count_var_name)
                model.add(employees_stats[e].count_vars[total_var_name] == shift_count).only_enforce_if(
                    employees_stats[e].count_vars[count_var_name])
                model.add(employees_stats[e].count_vars[total_var_name] != shift_count).only_enforce_if(
                    ~employees_stats[e].count_vars[count_var_name])

        if specific_input["applicable"](e):
            specific_var_name = f'cnst_{specific_input["prefix"]}_count_{e}'
            if "lambda" in specific_input:
                employees_stats[e].count_vars[specific_var_name] = model.new_int_var(0, get_employee_max_shifts(employees,e),
                                                                                     specific_var_name)
                specific_employee_works = [work[e, s, d] for s in range(num_shifts) for d in range(month_days) if
                                           specific_input["lambda"](e, s, d)]
                model.add(employees_stats[e].count_vars[specific_var_name] == sum(specific_employee_works))
            elif "set_lambda" in specific_input:
                employees_stats[e].count_vars[specific_var_name] = model.new_int_var(0, specific_input["max_value"],
                                                                                     specific_var_name)
                model.add(employees_stats[e].count_vars[specific_var_name] == sum(specific_input["set_lambda"](e)))
            else:
                print('wrong lamda')
                exit(1)

            for shift_count in range(start_shifts, get_employee_max_shifts(employees,e) + 1):
                soft_lim, hard_lim, penalty = specific_input["limits"][specific_input["index"](e)][shift_count][1]

                soft_var_name = f'cnst_{specific_input["prefix"]}_{e}_greater_than_{soft_lim}'
                hard_var_name = f'cnst_{specific_input["prefix"]}_{e}_greater_than_{hard_lim}'

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
                    if RELAX_HARD:
                        viol_key = f'viol_{specific_input["prefix"]}_upper_{e}'
                        if viol_key not in employees_stats[e].count_vars:
                            employees_stats[e].count_vars[viol_key] = register_violation(model, cost_literals, cost_coefficients,
                                f"{get_employee_name(employees,e)}: {specific_input['prefix']} shifts over hard MAX")
                        model.add_bool_or(~employees_stats[e].count_vars[f'{total_var_name}_{shift_count}'],
                                      ~employees_stats[e].count_vars[hard_var_name],
                                      employees_stats[e].count_vars[viol_key])
                    else:
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
                    employees_stats[e].add_var_weight(employees_stats[e].count_vars[soft_lim_var],penalty)

                #===================================================================================================
                soft_lim, hard_lim, penalty = specific_input["limits"][specific_input["index"](e)][shift_count][0]

                soft_var_name = f'cnst_{specific_input["prefix"]}_{e}_lower_than_{soft_lim}'
                hard_var_name = f'cnst_{specific_input["prefix"]}_{e}_lower_than_{hard_lim}'

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
                    if RELAX_HARD:
                        viol_key = f'viol_{specific_input["prefix"]}_lower_{e}'
                        if viol_key not in employees_stats[e].count_vars:
                            employees_stats[e].count_vars[viol_key] = register_violation(model, cost_literals, cost_coefficients,
                                f"{get_employee_name(employees,e)}: {specific_input['prefix']} shifts under hard MIN")
                        model.add_bool_or(~employees_stats[e].count_vars[f'{total_var_name}_{shift_count}'],
                                      ~employees_stats[e].count_vars[hard_var_name],
                                      employees_stats[e].count_vars[viol_key])
                    else:
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
                    employees_stats[e].add_var_weight(employees_stats[e].count_vars[soft_lim_var],penalty)


def print_broken_rules(solver):
    """After a RELAX_HARD solve, list which softened hard rules the solution had to break."""
    broken = [desc for (v, desc) in relaxations if solver.boolean_value(v)]
    print("\n" + "=" * 72)
    print("BEST-EFFORT SOLUTION — BROKEN HARD RULES")
    print("=" * 72)
    if not broken:
        print("None — the relaxed solve found a schedule that breaks no hard rule")
        print("(the original infeasibility may be a solver time-limit artifact).")
    else:
        print(f"{len(broken)} hard rule(s) had to be broken to build a schedule:\n")
        for desc in broken:
            print(f"  - {desc}")
        print("\nEach line above is a constraint that could not be satisfied; relaxing the")
        print("underlying data/config for these is what would make the month truly feasible.")
    print("=" * 72 + "\n")


def solve_best_effort(list_data):
    """Relax every hard rule to soft-with-penalty and solve, to get a schedule + broken-rule report."""
    global RELAX_HARD
    print("\n" + "=" * 72)
    print("BEST-EFFORT (RELAXED) SOLVE — producing a schedule despite infeasibility")
    print("=" * 72)
    RELAX_HARD = True
    try:
        cost_literals = []
        cost_coefficients = []
        work = {}
        virtual_work = {}
        black_listed = {}
        employees = []
        employees_stats = []
        format_input(list_data, employees, employees_stats)
        solve_shift_scheduling("", cost_literals, cost_coefficients, work,
                               virtual_work, black_listed, employees, employees_stats, [])
    finally:
        RELAX_HARD = False


def _loose_limits_table(n_indices=6, max_count=31):
    """A *_limits replacement that imposes no bound (lower 0, upper huge, no penalty)."""
    entry = {c: ((0, 0, 0), (99, 99, 0)) for c in range(max_count + 1)}
    return [dict(entry) for _ in range(n_indices)]


def _solve_full(list_data, diagnostic=True, zero_mins=False):
    """Build a fresh model from list_data and solve the whole month. Returns True if feasible."""
    cost_literals = []
    cost_coefficients = []
    work = {}
    virtual_work = {}
    black_listed = {}
    employees = []
    employees_stats = []
    format_input(list_data, employees, employees_stats)
    if zero_mins:
        for emp in employees:
            emp[2][0] = 0
    return solve_shift_scheduling("", cost_literals, cost_coefficients, work,
                                  virtual_work, black_listed, employees,
                                  employees_stats, [], diagnostic=diagnostic)


def report_capacity(list_data):
    """Aggregate necessary-condition check: required shifts per category vs available capacity."""
    employees = []
    stats = []
    format_input(list_data, employees, stats)
    n = len(employees)

    total = nights = internal = holiday = virtual = 0
    for d in range(month_days):
        if is_holiday(d):
            day_shifts = set(holiday_shifts)
        else:
            day_shifts = set(week_day_shifts)
        day_shifts = day_shifts.intersection(set(shift_groups[(d + month_starts_with_internal) % len(shift_groups)]))
        for s in range(len(shifts)):
            if shifts[s] in day_shifts:
                total += 1
                if is_night_shift(s):
                    nights += 1
                if is_internal(s):
                    internal += 1
                if is_holiday(d):
                    holiday += 1
        if (d + month_starts_with_internal) % len(shift_groups) == 1:
            virtual += 1

    sum_max = sum(get_employee_max_shifts(employees, e) for e in range(n))
    sum_min = sum(get_employee_min_shifts(employees, e) for e in range(n))

    # night capacity: sum over night-capable doctors of the largest night hard-cap in their MIN..MAX range
    night_cap = 0
    for e in range(n):
        if not (can_do_nights(employees, e) and get_employee_max_shifts(employees, e) > 0):
            continue
        idx = get_employee_extra_nights(employees, e)
        if idx >= len(night_limits):
            continue
        caps = [night_limits[idx][c][1][1] for c in range(get_employee_min_shifts(employees, e),
                                                           get_employee_max_shifts(employees, e) + 1)
                if c in night_limits[idx]]
        night_cap += max(caps) if caps else 0

    internal_cap = sum(get_employee_max_shifts(employees, e) for e in range(n) if can_do_internal(employees, e))
    virtual_eligible = sum(1 for e in range(n) if get_employee_virtual_shifts(employees, e) > 0)

    def line(label, req, cap, cap_label):
        flag = "  <-- SHORTFALL" if cap < req else ""
        print(f"  {label:24s} required={req:4d}   {cap_label}={cap:4d}{flag}")

    print("\n--- capacity report (necessary conditions) ---")
    line("total shifts", total, sum_max, "sum(MAX) ")
    if sum_min > total:
        print(f"  {'MIN totals':24s} sum(MIN)={sum_min:4d}   > total shifts={total:<4d}  <-- OVER-CONSTRAINED (MINs exceed demand)")
    else:
        print(f"  {'MIN totals':24s} sum(MIN)={sum_min:4d}   (total shifts={total})")
    line("night shifts", nights, night_cap, "night hard-cap sum")
    line("internal shifts", internal, internal_cap, "internal-capable MAX")
    line("virtual reserves", virtual, virtual_eligible * 2, "eligible x2       ")
    print(f"  {'holiday shifts':24s} required={holiday:4d}   (covered from sum(MAX)={sum_max})")


def diagnose_infeasibility(list_data):
    """Run when the full month is infeasible: capacity report + one-family-at-a-time relaxation."""
    print("\n" + "=" * 72)
    print("INFEASIBILITY DIAGNOSIS")
    print("=" * 72)

    report_capacity(list_data)

    print("\n--- constraint-family isolation (relax ONE family, re-solve full month) ---")
    print("    a family whose relaxation flips the month to FEASIBLE is a prime suspect")
    print(f"    (each re-solve capped at {diagnostic_solve_time}s; 'inconclusive' = hit time limit)\n")

    def report(label, res):
        verdict = "FEASIBLE when relaxed  <-- suspect" if res else "still infeasible"
        print(f"  relax {label:22s} -> {verdict}")

    loose = _loose_limits_table()
    for fam in ["night_limits", "holiday_limits", "internal_limits", "virtual_limits"]:
        saved = globals()[fam]
        globals()[fam] = loose
        try:
            report(fam, _solve_full(list_data))
        finally:
            globals()[fam] = saved

    saved = globals()["exclusive_groups"]
    globals()["exclusive_groups"] = []
    try:
        report("exclusive_groups", _solve_full(list_data))
    finally:
        globals()["exclusive_groups"] = saved

    report("MIN totals (set to 0)", _solve_full(list_data, zero_mins=True))

    saved = {fam: globals()[fam] for fam in ["night_limits", "holiday_limits", "internal_limits", "virtual_limits"]}
    for fam in saved:
        globals()[fam] = loose
    try:
        report("ALL *_limits", _solve_full(list_data))
    finally:
        for fam, val in saved.items():
            globals()[fam] = val
    print("=" * 72 + "\n")


def main(_):
    data = pandas.read_csv(filename).fillna("I")
    list_data = data.values.tolist()

    cost_literals = []
    cost_coefficients = []
    work = {}
    virtual_work = {}
    black_listed = {}
    employees = []
    employees_stats = []

    format_input(list_data, employees, employees_stats)

    for e in employees:
        print(e)

    if not solve_shift_scheduling(_OUTPUT_PROTO.value, cost_literals, cost_coefficients, work, virtual_work, black_listed, employees, employees_stats, []):
        diagnose_infeasibility(list_data)

        failed_days = []
        failed_windows = []

        for d in range(month_days):
            check_days = []
            check_days.append(d)
            cost_literals = []
            cost_coefficients = []
            work = {}
            virtual_work = {}
            black_listed = {}
            employees = []
            employees_stats = []

            format_input(list_data, employees, employees_stats)
            result = solve_shift_scheduling(_OUTPUT_PROTO.value, cost_literals, cost_coefficients, work, virtual_work, black_listed, employees, employees_stats, check_days)
            print(f"day {d+1} = {result}")
            if not result:
                failed_days.append(d + 1)

        for d in range(month_days -4):
            check_days = []
            check_days.append(d)
            check_days.append(d+1)
            check_days.append(d+2)
            check_days.append(d + 3)
            check_days.append(d + 4)
            cost_literals = []
            cost_coefficients = []
            work = {}
            virtual_work = {}
            black_listed = {}
            employees = []
            employees_stats = []

            format_input(list_data, employees, employees_stats)
            result = solve_shift_scheduling(_OUTPUT_PROTO.value, cost_literals, cost_coefficients, work, virtual_work, black_listed, employees, employees_stats, check_days)
            print(f"day {d+1} + 4 days = {result}")
            if not result:
                failed_windows.append(d + 1)

        print("\n" + "=" * 72)
        print("INFEASIBILITY VERDICT")
        print("=" * 72)
        if failed_days:
            print(f"LOCAL infeasibility on individual day(s): {failed_days}")
            print("  -> a single day cannot be staffed. Check availability (N marks), premium")
            print("     M1/A1/N1 slots that need level AA/A, and per-day 'P' conflicts on those days.")
        elif failed_windows:
            print(f"LOCAL infeasibility on 5-day window(s) starting at day(s): {failed_windows}")
            print("  -> no single day fails, but a run of days does. Check close-shift / close-night")
            print("     spacing and clustered availability around those days.")
        else:
            print("GLOBAL infeasibility: every single day AND every 5-day window is feasible on")
            print("its own, but the whole month is not. The blocker is a month-total capacity or")
            print("cross-family interaction (e.g. nights vs virtual reserves). See the capacity")
            print("report and constraint-family isolation above for the responsible family.")
        print("=" * 72)

        # produce a usable schedule anyway and report exactly which hard rules had to break
        solve_best_effort(list_data)


if __name__ == "__main__":
    app.run(main)
