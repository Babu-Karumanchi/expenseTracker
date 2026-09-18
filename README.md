# Spendly (◈)
**A lightweight, personal expense tracker for an Indian audience.**

Spendly helps users take control of their finances by tracking daily expenses, monitoring income, setting monthly budgets, and managing savings goals. It features a comprehensive analytics dashboard and AI-driven insights to help users understand their spending patterns and save more.

## 🚀 Key Features

- **Comprehensive Expense Tracking**: Log expenses with categories, dates, and descriptions. Full CRUD support via a seamless profile interface.
- **Income & Savings Management**: Track multiple income sources and set target-based savings goals with progress tracking.
- **Monthly Budgeting**: Set a monthly spending limit and visualize your progress with dynamic color-coded indicators (Green $\rightarrow$ Yellow $\rightarrow$ Red).
- **Advanced Analytics Dashboard**: 
  - **KPI Strip**: Instant view of total spend, transaction count, and average spend.
  - **Spending Trends**: Monthly spend visualization using inline SVG charts.
  - **Category Analysis**: High-to-low breakdown of spending by category.
  - **Behavioral Insights**: Average spending analysis by day of the week.
- **AI Spending Insights**: Integration with the Groq API to provide professional, actionable financial tips based on the last 3 months of spending data.
- **Smart Filtering**: Filter transactions and statistics by custom date ranges or presets (This Month, Last 3/6/12 Months).
- **Secure Authentication**: User registration and login system with password hashing (Werkzeug) and CSRF protection.

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, Flask
- **Database**: SQLite (with Foreign Key enforcement)
- **Frontend**: Jinja2 Templates, Vanilla JavaScript, CSS3
- **AI Integration**: Groq API (via `urllib`)

## 📁 Project Structure

```text
spendly/
├── app.py              # Application routes and business logic
├── database/
│   └── db.py           # SQLite schema and database helper functions
├── static/              # Frontend assets
│   ├── css/            # Global and page-specific styles
│   └── js/             # Vanilla JS for modals and AJAX updates
├── templates/           # Jinja2 HTML templates
├── tests/              # Pytest suite for features and DB helpers
├── requirements.txt     # Project dependencies
└── spendly.db          # SQLite database file (auto-generated)
```

## ⚙️ Installation & Setup

### Prerequisites
- Python 3.10 or higher
- A Groq API Key (optional, for AI insights)

### Setup
1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd spendly
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configuration**:
   Create a `.env` file in the root directory:
   ```env
   SPENDLY_SECRET_KEY=your_secure_random_secret_key
   GROQ_API_KEY=your_groq_api_key_here
   GROQ_MODEL=openai/gpt-oss-20b
   ```

## 🏃 Running the Project

### Local Development
Start the Flask server:
```bash
python app.py
```
The application will be available at `http://127.0.0.1:5001`.

### Testing
Run the complete test suite using `pytest`:
```bash
pytest
```
To run a specific test file:
```bash
pytest tests/test_feature_name.py
```

## 📖 Usage Examples

1. **Register & Login**: Create an account to start tracking your finances.
2. **Log Expenses**: Use the "Add Expense" modal on your profile to record a spend (e.g., ₹450 for "Food").
3. **Set Budget**: Navigate to the Budget page to set your monthly limit (e.g., ₹20,000).
4. **Analyze**: Visit the Analytics page to see where your money goes and get AI-generated tips on the Insights page.

## 🤝 Contribution Guidelines

1. **Branching**: Create a feature branch from `main` (e.g., `feature/new-stat-card`).
2. **Style**: Follow PEP 8 for Python and use `url_for()` for all internal links in templates.
3. **DB Logic**: All database queries must reside in `database/db.py`. Never write SQL directly in `app.py`.
4. **Frontend**: Stick to Vanilla JS; avoid adding heavy frameworks or npm packages.
5. **Testing**: Ensure all new features are covered by pytest cases in the `tests/` directory.

## 📄 License
This project is for educational purposes. Please refer to the repository license for more details.
