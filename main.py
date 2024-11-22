import requests
import json
import logging
from collections import Counter

# Configure logging
logging.basicConfig(level=logging.INFO)

# List of loan IDs for dynamic URL generation
application_id = [22019]  # Add more IDs as needed

# API URL templates for SACC Loan calculations
API_URL_LESS_THAN_300 = "https://app.cashfaster.com.au/bank-statement/loan-calculator/{amount}/2/fortnightly"
API_URL_GREATER_OR_EQUAL_300 = "https://app.cashfaster.com.au/bank-statement/loan-calculator/{amount}/5/fortnightly"

# 1. Data Extraction
def fetch_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Data extraction failed for URL {url}: {e}")
        return None

# 2. Define Income and Expense Categories
income_categories = {
    "Wages - Monthly": "Wages",
    "Centrelink - Monthly": "Centrelink",
}

expense_categories = {
    "SACC Loans - Monthly": "SACC",
    "Debt Collection - Monthly": "Debt Collection"
}

# Initialize category totals
def initialize_category_totals():
    category_totals = {label: 0.0 for label in income_categories.values()}
    category_totals.update({label: 0.0 for label in expense_categories.values()})
    category_totals["Living Expenses"] = 0.0  # Initialize Living Expenses separately
    return category_totals

# 3. Parse and Clean Data
def parse_decision_metrics(raw_data):
    customer_info = raw_data.get("illionCustomerInfo", {})
    decision_metrics_str = customer_info.get("decisionMetrics", "[]")
    try:
        decision_metrics = json.loads(decision_metrics_str)
        return decision_metrics
    except json.JSONDecodeError:
        logging.error("Failed to parse decision metrics.")
        return []

def parse_statement_analysis(raw_data):
    bank_accounts = raw_data.get("illionBankAccount", [])
    all_analyses = []
    
    for account in bank_accounts:
        statement_analysis_str = account.get("statementAnalysis", "[]")
        try:
            statement_analysis = json.loads(statement_analysis_str)
            if isinstance(statement_analysis, list):
                all_analyses.extend(statement_analysis)
        except json.JSONDecodeError:
            logging.error("Failed to parse statement analysis.")
            continue
    
    return all_analyses

def get_amount_from_analysis_category(analysis_category, key="totalAmount"):
    for point in analysis_category.get("analysisPoints", []):
        if point.get("name") == key:
            try:
                value = point.get("value", 0)
                return abs(float(value)) if isinstance(value, (str, int, float)) else 0.0
            except (ValueError, TypeError):
                logging.error(f"Error converting value for {key}")
                return 0.0

    amount = 0.0
    transaction_groups = analysis_category.get("transactionGroups", [])
    for group in transaction_groups:
        transactions = group.get("transactions", [])
        for transaction in transactions:
            try:
                transaction_amount = transaction.get("amount", 0)
                amount += abs(float(transaction_amount))
            except (ValueError, TypeError):
                continue

    return amount

def get_top_recurring_transaction_amount(transactions):
    amounts = [
        abs(float(transaction.get("amount", 0)))
        for transaction in transactions
        if isinstance(transaction.get("amount"), (int, float)) and transaction.get("amount") < 0
    ]
    if not amounts:
        return 0.0

    frequency = Counter(amounts)
    for amount, count in frequency.items():
        if count >= 3:
            return amount

    return 0.0

def calculate_sacc_loans(statement_analysis):
    sacc_results = {}
    for entry in statement_analysis:
        if not isinstance(entry, dict):
            continue

        analysis_category = entry.get("analysisCategory", {})
        if analysis_category.get("name") != "SACC Loans":
            continue

        for group in analysis_category.get("transactionGroups", []):
            third_party = group.get("name", "Unknown")
            transactions = group.get("transactions", [])
            
            if isinstance(transactions, str):
                try:
                    transactions = json.loads(transactions)
                except json.JSONDecodeError:
                    logging.error("Failed to parse transactions JSON.")
                    continue

            for transaction in transactions:
                if not isinstance(transaction, dict):
                    continue

                tags = transaction.get("tags", [])
                is_credit = any(
                    isinstance(tag, dict) and tag.get("creditDebit") == "credit"
                    for tag in tags
                )
                
                if is_credit:
                    amount = transaction.get("amount", 0)
                    if isinstance(amount, (int, float)) and amount > 0:
                        sacc_results[third_party] = amount
                        break

    sacc_totals = {}
    for third_party, total_amount in sacc_results.items():
        try:
            if total_amount < 300:
                api_url = API_URL_LESS_THAN_300.format(amount=int(total_amount))
            else:
                api_url = API_URL_GREATER_OR_EQUAL_300.format(amount=int(total_amount))

            logging.info(f"Calling API for {third_party}: {api_url}")
            response = requests.get(api_url)
            response.raise_for_status()

            repayment_amount_str = response.json().get("repayment_amount", "0.0")
            try:
                repayment_amount = float(repayment_amount_str)
            except ValueError:
                logging.error(f"Invalid repayment amount format for {third_party}: {repayment_amount_str}")
                repayment_amount = 0.0

            sacc_totals[third_party] = repayment_amount
            logging.info(f"{third_party} SACC Loan: ${repayment_amount:.2f}")

        except requests.exceptions.RequestException as e:
            logging.error(f"API call failed for {third_party}: {e}")

    return sacc_totals


def accumulate_metrics_from_statement_analysis(statement_analysis, category_totals):
    logging.info("Parsing and accumulating metrics from all statement analysis entries...")

    # Reset all values to ensure clean calculation
    category_totals["Rent"] = 0.0
    category_totals["Centrelink"] = 0.0
    category_totals["Gambling"] = 0.0
    category_totals["SACC"] = {}  # Change to a dictionary
    category_totals["Debt Collection"] = 0.0
    category_totals["Wages"] = 0.0
    category_totals["Insurance"] = 0.0

    # Calculate SACC loans first
    sacc_totals = calculate_sacc_loans(statement_analysis)
    if sacc_totals:
        category_totals["SACC"] = sacc_totals
        logging.info(f"Total SACC Loans: ${sum(sacc_totals.values()):.2f}")

    rent_found = False

    for item in statement_analysis:
        if not isinstance(item, dict):
            continue

        analysis_category = item.get("analysisCategory", {})
        category_name = analysis_category.get("name")

        if category_name == "Rent":
            rent_found = True
            transactions = analysis_category.get("transactionGroups", [])
            all_transactions = []
            for group in transactions:
                all_transactions.extend(group.get("transactions", []))
            rent_amount = get_top_recurring_transaction_amount(all_transactions)
            category_totals["Rent"] += rent_amount

        elif category_name == "Insurance":
            insurance_amount = get_amount_from_analysis_category(analysis_category, "averageTransactionAmount")
            if insurance_amount > 0:
                category_totals["Insurance"] += insurance_amount

        elif category_name == "Wages":
            wages_amount = get_amount_from_analysis_category(analysis_category, "averageTransactionAmount")
            if wages_amount > 0:
                category_totals["Wages"] += wages_amount

        elif category_name == "Centrelink":
            centrelink_amount = get_amount_from_analysis_category(analysis_category, "averageTransactionAmount")
            if centrelink_amount > 0:
                category_totals["Centrelink"] = centrelink_amount  # Use = instead of += to avoid double counting

        elif category_name == "Gambling":
            total_debits = sum(
                float(entry.get("value", 0))
                for entry in analysis_category.get("analysisPoints", [])
                if entry.get("name") == "totalAmountDebits"
            )
            total_credits = sum(
                float(entry.get("value", 0))
                for entry in analysis_category.get("analysisPoints", [])
                if entry.get("name") == "totalAmountCredits"
            )
            net_gambling = total_debits - total_credits
            if net_gambling > 0:
                gambling_fortnightly = round(((net_gambling / 6) * 12) / 26, 2)
            else:
                gambling_fortnightly = 0.0
            category_totals["Gambling"] += gambling_fortnightly

    if not rent_found:
        category_totals["Rent"] = 0.0

def categorize_data(decision_metrics, category_totals, statement_analysis):
    # First accumulate statement analysis metrics
    accumulate_metrics_from_statement_analysis(statement_analysis, category_totals)
    
    # Store the Centrelink value from statement analysis
    centrelink_from_statement = category_totals["Centrelink"]

    # Carefully calculate living expenses by summing up all expenses
    living_expenses_total = 0.0
    rent_found = False

    for metric in decision_metrics:
        name = metric.get("name")
        value_str = str(metric.get("value", "0.0"))

        # Skip Rent until found
        if name == "Rent - Monthly":
            rent_found = True
            continue
        
        # Only start summing after Rent is encountered
        if not rent_found:
            continue

        # Skip Insurance and (Once off) entries
        if name == "Insurance - Monthly" or "(Once off)" in value_str:
            continue

        try:
            # Remove $ and convert to float
            value = float(value_str.replace("$", "").replace(" (Once off)", ""))
        except ValueError:
            value = 0.0

        # Skip Wages, Centrelink, and Loan-specific categories
        if name in ["Wages - Monthly", "Centrelink - Monthly", "SACC Loans - Monthly", "All Loans - Monthly"]:
            continue

        # Add to living expenses total
        living_expenses_total += value

    # Convert monthly to fortnightly: (*12 months) / (26 fortnights)
    category_totals["Living Expenses"] = round((living_expenses_total * 12) / 26, 2)

    # Ensure Centrelink value stays as per statement analysis
    category_totals["Centrelink"] = centrelink_from_statement


def calculate_totals(category_totals):
    total_income = round(sum(category_totals[cat] for cat in income_categories.values()), 2)
    
    # Calculate total SACC loans
    total_sacc_loans = sum(category_totals["SACC"].values()) if isinstance(category_totals["SACC"], dict) else category_totals["SACC"]
    
    # Calculate total expenses
    total_expenses = round(
        total_sacc_loans + 
        category_totals.get("Debt Collection", 0.0) + 
        category_totals.get("Living Expenses", 0.0), 
        2
    )
    
    surplus = round(total_income - total_expenses, 2)
    return total_income, total_expenses, surplus

def format_output(raw_data, category_totals, total_income, total_expenses, surplus, loan_id):
    account_info = raw_data.get("illionBankAccount", [{}])[0]
    account_holder = account_info.get("account_holder", "Unknown")

    link = f"https://admin.cashfaster.com.au/admin/loan/{loan_id}/show {account_holder}"

    # Format SACC Loans details
    sacc_loans_details = " ".join([f"{party} SACC Loan: ${amount:.2f}" for party, amount in category_totals.get("SACC", {}).items()])

    output = f"""
    {link}
    Wages: ${category_totals.get("Wages", 0):.2f}
    Centrelink: ${category_totals.get("Centrelink", 0):.2f}
    Total Income: ${total_income:.2f}
    SACC Loans: {{{sacc_loans_details}}}
    Non-SACC Loans: $0.00
    Wage Advance: $0.00
    BNPL: $0.00
    Debt Collection: ${category_totals.get("Debt Collection", 0):.2f}
    Living Expenses: ${category_totals.get("Living Expenses", 0):.2f}
    Rent: ${category_totals.get("Rent", 0):.2f}
    Gambling: ${category_totals.get("Gambling", 0):.2f}
    Insurance: ${category_totals.get("Insurance", 0):.2f}
    Total Expenses: ${total_expenses:.2f}
    """
    return output

def save_all_outputs_to_file(all_outputs):
    try:
        with open("all_loan_outputs.txt", "w") as text_file:
            text_file.writelines(all_outputs)
        logging.info("All loan outputs saved to all_loan_outputs.txt")
    except IOError as e:
        logging.error(f"Failed to save outputs: {e}")

def main():
    all_outputs = []
    for loan_id in application_id:
        url = f"https://admin.cashfaster.com.au/bank-statement/{loan_id}"
        raw_data = fetch_data(url)
        if raw_data is None:
            continue

        decision_metrics = parse_decision_metrics(raw_data)
        statement_analysis = parse_statement_analysis(raw_data)
        category_totals = initialize_category_totals()
        categorize_data(decision_metrics, category_totals, statement_analysis)

        total_income, total_expenses, surplus = calculate_totals(category_totals)
        output = format_output(raw_data, category_totals, total_income, total_expenses, surplus, loan_id)
        all_outputs.append(output)

    save_all_outputs_to_file(all_outputs)

if __name__ == "__main__":
    main()