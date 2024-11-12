#!/usr/bin/env python3

from absl import app
from absl import flags

from google.protobuf import text_format
from ortools.sat.python import cp_model
from tabulate import tabulate

_OUTPUT_PROTO = flags.DEFINE_string(
    "output_proto", "", "Output file to write the cp_model proto to."
)
_PARAMS = flags.DEFINE_string(
    "params", "max_time_in_seconds:60.0", "Sat solver parameters."
)




def solve_shift_scheduling(params: str, output_proto: str):
    """Solves the shift scheduling problem."""
    # Data
    num_employees = 50
    num_weeks = 4
    week = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    shifts = ["IM","M1", "M2", "IA", "A1", "A2", "N1", "N2"]

    month_first_day = "Th"
    month_days = 31
    public_holidays = [5]

    shift_groups = [
        ["IM", "IA"],
        ["M1", "M2", "A1", "A2", "N1", "N2"]
    ]

    week_day_shifts = ["IA", "A1", "A2", "N1", "N2"]
    holiday_shifts = ["IM","M1", "M2", "IA", "A1", "A2", "N1", "N2"]

    levels = {
        "L1": ["IM", "IA"],
        "L2": ["IM", "IA", "M2", "A2"],
        "L3": ["IM", "IA", "M2", "A2", "N2"],
        "L4": ["M1", "M2", "IM", "IA", "A1", "A2", "N1", "N2"]
    }

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
        ("P21", "L04"),
        ("P22", "L04"),
    ]

    num_employees = len(employees)
    num_shifts = len(shifts)
    day_index = week.index(month_first_day)

    model = cp_model.CpModel()

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

    for d in range(month_days):
            is_holiday = False

            if d + 1 in public_holidays:
                is_holiday = True
            elif (d + day_index) % 7 in [5,6]:
                is_holiday = True

            day_shifts = week_day_shifts
            if is_holiday:
                day_shifts = holiday_shifts

            for s in range(num_shifts):
                works = [work[e, s, d] for e in range(num_employees)]
                if shifts[s] in day_shifts:
                    model.add(1 == sum(works))
                else:
                    model.add(0 == sum(works))



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
            line = [d, week[(d + day_index) %7]]
            for s in range(num_shifts):
                shift_given = False
                for e in range(num_employees):
                    if solver.boolean_value(work[e, s, d]):
                        line.append(employees[e][0])
                        shift_given = True
                if not shift_given:
                    line.append("")
            output.append(line)

        print(tabulate(output, tablefmt="html"))



def main(_):
    solve_shift_scheduling(_PARAMS.value, _OUTPUT_PROTO.value)


if __name__ == "__main__":
    app.run(main)
