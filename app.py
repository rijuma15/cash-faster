from fastapi import FastAPI, HTTPException
from main import fetch_data, initialize_category_totals, parse_decision_metrics, parse_statement_analysis, categorize_data, calculate_totals, format_output

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Welcome to the Loan Processing API"}

@app.get("/process-loan/{loan_id}")
def process_loan(loan_id: int):
    url = f"https://admin.cashfaster.com.au/bank-statement/{loan_id}"
    raw_data = fetch_data(url)
    if raw_data is None:
        raise HTTPException(status_code=404, detail=f"Loan ID {loan_id} not found.")

    decision_metrics = parse_decision_metrics(raw_data)
    statement_analysis = parse_statement_analysis(raw_data)
    category_totals = initialize_category_totals()
    categorize_data(decision_metrics, category_totals, statement_analysis)

    total_income, total_expenses, surplus = calculate_totals(category_totals)
    output = format_output(raw_data, category_totals, total_income, total_expenses, surplus, loan_id)
    
    return {"output": output}
