//+------------------------------------------------------------------+
//|                                   IntradayVolatilityBreakout.mq5 |
//|                    Copyright 2025, RobustifyTrading               |
//|                        All rights reserved                        |
//+------------------------------------------------------------------+
#property copyright "RobustifyTrading"
#property link      ""
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>

//--- Confirmation timeframe restricted to three structurally meaningful values.
//    Keeps the optimizer from finding spurious edges on arbitrary candle sizes.
enum ENUM_CONFIRM_TF
{
   CONFIRM_M5  = PERIOD_M5,   // M5
   CONFIRM_M10 = PERIOD_M10,  // M10
   CONFIRM_M15 = PERIOD_M15,  // M15
};

enum ENUM_REGIME_MODE
{
   REGIME_LOW_VOLATILITY  = 0,  // Low Volatility Regime
   REGIME_HIGH_VOLATILITY = 1   // High Volatility Regime
};

enum ENUM_TRADE_DIRECTION
{
   TRADE_BOTH       = 0,  // Both Directions
   TRADE_LONG_ONLY  = 1,  // Long Only
   TRADE_SHORT_ONLY = 2   // Short Only
};

//--- Input Parameters
input group "Breakout Parameters"
input int                ATR_Period              = 14;       // ATR Period (Daily) — fixed, not optimized
input double             ATR_Multiplier          = 0.25;     // ATR Multiplier for Breakout Levels
input double             Stop_ATR_Multiplier     = 0.25;     // ATR Multiplier for Stop Loss
input bool               Use_Candle_Close        = true;     // Require Candle Close Confirmation
input ENUM_CONFIRM_TF    Confirmation_Timeframe  = CONFIRM_M10; // Confirmation Timeframe

input group "Risk / Reward"
// RR_Ratio fixes TP = SL × RR_Ratio so R:R is constant regardless of Stop_ATR_Multiplier.
// Do NOT optimize this — set it by market structure rationale (e.g. 2.0 for breakouts).
input double             RR_Ratio               = 2.0;      // Risk:Reward Ratio (TP = SL × ratio)

input group "Regime Filter"
// Periods are fixed at structurally meaningful values (3-day vs 20-day ATR).
// Optimizing these converts the regime filter into another fitted parameter.
input double             ATR_Regime_Factor       = 1.0;      // Regime Threshold Factor
input ENUM_REGIME_MODE   Regime_Filter_Mode      = REGIME_LOW_VOLATILITY; // Regime Mode

input group "Trade Direction"
input ENUM_TRADE_DIRECTION Trade_Direction       = TRADE_BOTH; // Allowed Trade Direction

input group "Spread Filter"
// Rejects entries when the spread exceeds this threshold.
// Set to ~3× your broker's typical Gold spread. Do NOT optimize.
input int                Max_Spread_Points       = 30;       // Max Spread to Enter (points)

input group "Trading Hours"
input string             Entry_Time              = "16:30";  // Entry Window Start (HH:MM)
input string             Max_Entry_Time          = "18:05";  // Latest Entry Time (HH:MM)
input string             Exit_Time               = "22:55";  // Close All Positions Time (HH:MM)

input group "Position Management"
input double             Fixed_Risk_Amount       = 500.0;    // Fixed Risk Amount (Account Currency)

input group "Risk Management"
input int                Magic_Number            = 123456;   // Magic Number

//--- Global Variables
CTrade   g_trade;
double   g_atr_value;
double   g_entry_open_price;
double   g_upper_level;
double   g_lower_level;
double   g_stop_distance;
double   g_tp_distance;
bool     g_setup_ready;
bool     g_levels_calculated;
bool     g_trade_taken;
datetime g_last_bar_time;
datetime g_last_confirm_bar;
int      g_atr_handle;
int      g_atr_long_handle;   // 20-day ATR for regime baseline
int      g_atr_short_handle;  // 3-day ATR for current regime
int      g_entry_hour,     g_entry_min;
int      g_max_entry_hour, g_max_entry_min;
int      g_exit_hour,      g_exit_min;

// Fixed regime filter periods — not optimized
#define REGIME_SHORT_PERIOD 3
#define REGIME_LONG_PERIOD  20

//+------------------------------------------------------------------+
//| Initialization                                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber(Magic_Number);
   g_trade.SetDeviationInPoints(10);
   g_trade.SetTypeFilling(ORDER_FILLING_FOK);

   g_atr_handle = iATR(_Symbol, PERIOD_D1, ATR_Period);
   if(g_atr_handle == INVALID_HANDLE)
   {
      Print("Error: Failed to create ATR indicator handle");
      return INIT_FAILED;
   }

   g_atr_long_handle = iATR(_Symbol, PERIOD_D1, REGIME_LONG_PERIOD);
   if(g_atr_long_handle == INVALID_HANDLE)
   {
      Print("Error: Failed to create long-term ATR handle");
      return INIT_FAILED;
   }

   g_atr_short_handle = iATR(_Symbol, PERIOD_D1, REGIME_SHORT_PERIOD);
   if(g_atr_short_handle == INVALID_HANDLE)
   {
      Print("Error: Failed to create short-term ATR handle");
      return INIT_FAILED;
   }

   if(!ParseTime(Entry_Time, g_entry_hour, g_entry_min))
   {
      Print("Error: Invalid Entry_Time format. Use HH:MM");
      return INIT_FAILED;
   }
   if(!ParseTime(Max_Entry_Time, g_max_entry_hour, g_max_entry_min))
   {
      Print("Error: Invalid Max_Entry_Time format. Use HH:MM");
      return INIT_FAILED;
   }
   if(!ParseTime(Exit_Time, g_exit_hour, g_exit_min))
   {
      Print("Error: Invalid Exit_Time format. Use HH:MM");
      return INIT_FAILED;
   }

   int entry_mins     = g_entry_hour * 60 + g_entry_min;
   int max_entry_mins = g_max_entry_hour * 60 + g_max_entry_min;
   int exit_mins      = g_exit_hour * 60 + g_exit_min;

   if(entry_mins >= max_entry_mins)
   {
      Print("Error: Entry_Time must be earlier than Max_Entry_Time");
      return INIT_FAILED;
   }
   if(max_entry_mins >= exit_mins)
   {
      Print("Error: Max_Entry_Time must be earlier than Exit_Time");
      return INIT_FAILED;
   }
   if(RR_Ratio <= 0)
   {
      Print("Error: RR_Ratio must be positive");
      return INIT_FAILED;
   }

   ResetDailyState();

   Print("IntradayVolatilityBreakout v2.00 initialized");
   Print("ATR Period: ",        ATR_Period,
         " | Breakout Mult: ",  ATR_Multiplier,
         " | Stop Mult: ",      Stop_ATR_Multiplier,
         " | RR Ratio: ",       RR_Ratio,
         " | TP Mult (eff): ",  NormalizeDouble(Stop_ATR_Multiplier * RR_Ratio, 4));
   Print("Regime: ATR(", REGIME_SHORT_PERIOD, "d) vs ATR(", REGIME_LONG_PERIOD,
         "d) × ", ATR_Regime_Factor, " | Mode: ", EnumToString(Regime_Filter_Mode));
   Print("Direction: ", DirectionToString(),
         " | Confirm TF: ",     EnumToString((ENUM_TIMEFRAMES)Confirmation_Timeframe),
         " | Candle close: ",   Use_Candle_Close ? "Yes" : "No");
   Print("Max Spread: ", Max_Spread_Points, " pts",
         " | Hours: ", Entry_Time, " - ", Max_Entry_Time, " | Exit: ", Exit_Time);
   Print("Risk: ", Fixed_Risk_Amount, " ", AccountInfoString(ACCOUNT_CURRENCY));

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Deinitialization                                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_atr_handle != INVALID_HANDLE)       IndicatorRelease(g_atr_handle);
   if(g_atr_long_handle != INVALID_HANDLE)  IndicatorRelease(g_atr_long_handle);
   if(g_atr_short_handle != INVALID_HANDLE) IndicatorRelease(g_atr_short_handle);
}

//+------------------------------------------------------------------+
//| Main Tick Handler                                                 |
//+------------------------------------------------------------------+
void OnTick()
{
   if(PositionSelect(_Symbol))
   {
      if(ShouldClosePosition())
      {
         CloseAllPositions();
         return;
      }
   }

   if(Use_Candle_Close)
   {
      datetime bar_time = iTime(_Symbol, (ENUM_TIMEFRAMES)Confirmation_Timeframe, 0);
      if(bar_time == g_last_confirm_bar)
         return;
      g_last_confirm_bar = bar_time;
   }

   datetime current_bar = iTime(_Symbol, PERIOD_M1, 0);
   if(current_bar != g_last_bar_time)
      g_last_bar_time = current_bar;

   if(IsNewDay())
   {
      ResetDailyState();
      Print("New trading day detected");
   }

   if(!g_levels_calculated && IsAtOrPastTime(g_entry_hour, g_entry_min))
   {
      if(CalculateLevels())
      {
         g_levels_calculated = true;
         g_setup_ready       = true;
         PrintLevels();
      }
   }

   if(!g_setup_ready || g_trade_taken || !g_levels_calculated)
      return;

   if(!IsInEntryWindow())
      return;

   if(PositionSelect(_Symbol))
      return;

   if(!PassesSpreadFilter())
      return;

   if(!PassesRegimeFilter())
      return;

   EvaluateSignals();
}

//+------------------------------------------------------------------+
//| Spread Filter                                                     |
//+------------------------------------------------------------------+
bool PassesSpreadFilter()
{
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > Max_Spread_Points)
   {
      Print("Entry skipped: spread ", spread, " > max ", Max_Spread_Points);
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Core Signal Evaluation — breakout direction only, no reverse mode |
//+------------------------------------------------------------------+
void EvaluateSignals()
{
   double price = GetSignalPrice();
   if(price <= 0)
      return;

   bool upper_hit = (price >= g_upper_level);
   bool lower_hit = (price <= g_lower_level);

   if(upper_hit && (Trade_Direction == TRADE_BOTH || Trade_Direction == TRADE_LONG_ONLY))
      OpenLong("Breakout Long");

   if(lower_hit && (Trade_Direction == TRADE_BOTH || Trade_Direction == TRADE_SHORT_ONLY))
      OpenShort("Breakout Short");
}

//+------------------------------------------------------------------+
//| Get Signal Price Based on Confirmation Mode                       |
//+------------------------------------------------------------------+
double GetSignalPrice()
{
   if(Use_Candle_Close)
      return iClose(_Symbol, (ENUM_TIMEFRAMES)Confirmation_Timeframe, 1);

   return SymbolInfoDouble(_Symbol, SYMBOL_LAST);
}

//+------------------------------------------------------------------+
//| Regime Filter — fixed 3-day vs 20-day ATR comparison             |
//+------------------------------------------------------------------+
bool PassesRegimeFilter()
{
   double long_buf[], short_buf[];
   ArraySetAsSeries(long_buf,  true);
   ArraySetAsSeries(short_buf, true);

   if(CopyBuffer(g_atr_long_handle,  0, 1, 1, long_buf)  <= 0) return false;
   if(CopyBuffer(g_atr_short_handle, 0, 1, 1, short_buf) <= 0) return false;

   double short_atr = short_buf[0];
   double threshold = long_buf[0] * ATR_Regime_Factor;

   if(Regime_Filter_Mode == REGIME_LOW_VOLATILITY)
      return (short_atr < threshold);
   else
      return (short_atr > threshold);
}

//+------------------------------------------------------------------+
//| Calculate Breakout Levels                                         |
//+------------------------------------------------------------------+
bool CalculateLevels()
{
   double buf[];
   ArraySetAsSeries(buf, true);

   if(CopyBuffer(g_atr_handle, 0, 1, 1, buf) <= 0)
   {
      Print("Error: Failed to read ATR buffer");
      return false;
   }

   g_atr_value = buf[0];

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = g_entry_hour;
   dt.min  = g_entry_min;
   dt.sec  = 0;

   int shift = iBarShift(_Symbol, PERIOD_M1, StructToTime(dt));
   if(shift < 0)
   {
      Print("Error: Could not locate bar at entry time");
      return false;
   }

   g_entry_open_price = iOpen(_Symbol, PERIOD_M1, shift);
   if(g_entry_open_price <= 0)
   {
      Print("Error: Invalid open price at entry time");
      return false;
   }

   g_upper_level   = g_entry_open_price + ATR_Multiplier       * g_atr_value;
   g_lower_level   = g_entry_open_price - ATR_Multiplier       * g_atr_value;
   g_stop_distance = Stop_ATR_Multiplier                        * g_atr_value;
   g_tp_distance   = Stop_ATR_Multiplier * RR_Ratio             * g_atr_value;

   return true;
}

//+------------------------------------------------------------------+
//| Open Long Position                                                |
//+------------------------------------------------------------------+
void OpenLong(string comment)
{
   double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double sl   = ask - g_stop_distance;
   double tp   = ask + g_tp_distance;
   double lots = CalculateLotSize(g_stop_distance);

   if(lots <= 0)
   {
      Print("Long skipped: lot size is zero");
      return;
   }

   if(g_trade.Buy(lots, _Symbol, ask, sl, tp, comment))
   {
      Print("Long opened @ ", ask, " | Lots: ", lots,
            " | SL: ", sl, " | TP: ", tp, " | RR: ", RR_Ratio, " | ", comment);
      g_trade_taken = true;
   }
   else
      Print("Long failed. Error: ", GetLastError());
}

//+------------------------------------------------------------------+
//| Open Short Position                                               |
//+------------------------------------------------------------------+
void OpenShort(string comment)
{
   double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl   = bid + g_stop_distance;
   double tp   = bid - g_tp_distance;
   double lots = CalculateLotSize(g_stop_distance);

   if(lots <= 0)
   {
      Print("Short skipped: lot size is zero");
      return;
   }

   if(g_trade.Sell(lots, _Symbol, bid, sl, tp, comment))
   {
      Print("Short opened @ ", bid, " | Lots: ", lots,
            " | SL: ", sl, " | TP: ", tp, " | RR: ", RR_Ratio, " | ", comment);
      g_trade_taken = true;
   }
   else
      Print("Short failed. Error: ", GetLastError());
}

//+------------------------------------------------------------------+
//| Calculate Lot Size from Fixed Risk                                |
//+------------------------------------------------------------------+
double CalculateLotSize(double sl_distance)
{
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double min_lot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lot_step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(tick_size <= 0 || tick_value <= 0 || sl_distance <= 0)
   {
      Print("Error: Invalid params in CalculateLotSize (tick_size=", tick_size,
            " tick_value=", tick_value, " sl_distance=", sl_distance, ")");
      return 0;
   }

   double risk_per_lot = (sl_distance / tick_size) * tick_value;
   double lots         = Fixed_Risk_Amount / risk_per_lot;

   lots = MathFloor(lots / lot_step) * lot_step;
   lots = NormalizeDouble(lots, 2);
   lots = MathMax(lots, min_lot);
   lots = MathMin(lots, max_lot);

   return lots;
}

//+------------------------------------------------------------------+
//| Close All Positions                                               |
//+------------------------------------------------------------------+
void CloseAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
      {
         if(PositionGetString(POSITION_SYMBOL)  == _Symbol &&
            PositionGetInteger(POSITION_MAGIC)  == Magic_Number)
         {
            g_trade.PositionClose(ticket);
            Print("Position closed: #", ticket);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Check If Existing Position Should Be Closed                       |
//+------------------------------------------------------------------+
bool ShouldClosePosition()
{
   if(!PositionSelect(_Symbol))
      return false;

   datetime pos_time = (datetime)PositionGetInteger(POSITION_TIME);

   MqlDateTime pos_dt, now_dt;
   TimeToStruct(pos_time,      pos_dt);
   TimeToStruct(TimeCurrent(), now_dt);

   if(pos_dt.day != now_dt.day || pos_dt.mon != now_dt.mon || pos_dt.year != now_dt.year)
   {
      Print("Stale position from previous day detected");
      return true;
   }

   int now_mins  = now_dt.hour * 60 + now_dt.min;
   int exit_mins = g_exit_hour * 60  + g_exit_min;

   if(now_mins >= exit_mins)
   {
      Print("Exit time reached");
      return true;
   }

   return false;
}

//+------------------------------------------------------------------+
//| Reset Daily State                                                 |
//+------------------------------------------------------------------+
void ResetDailyState()
{
   g_setup_ready       = false;
   g_levels_calculated = false;
   g_trade_taken       = false;
   g_entry_open_price  = 0;
}

//+------------------------------------------------------------------+
//| New Day Check                                                     |
//+------------------------------------------------------------------+
bool IsNewDay()
{
   static int last_day = -1;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(dt.day != last_day)
   {
      last_day = dt.day;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Time Comparisons                                                  |
//+------------------------------------------------------------------+
bool IsAtOrPastTime(int hour, int minute)
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (dt.hour * 60 + dt.min >= hour * 60 + minute);
}

bool IsInEntryWindow()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int now = dt.hour * 60 + dt.min;
   return (now >= g_entry_hour     * 60 + g_entry_min &&
           now <  g_max_entry_hour * 60 + g_max_entry_min);
}

//+------------------------------------------------------------------+
//| Parse HH:MM Time String                                          |
//+------------------------------------------------------------------+
bool ParseTime(string time_str, int &hour, int &minute)
{
   string parts[];
   if(StringSplit(time_str, ':', parts) != 2)
      return false;

   hour   = (int)StringToInteger(parts[0]);
   minute = (int)StringToInteger(parts[1]);

   return (hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59);
}

//+------------------------------------------------------------------+
//| Print Levels to Journal                                           |
//+------------------------------------------------------------------+
void PrintLevels()
{
   Print("Levels | Open: ",  g_entry_open_price,
         " | Upper: ",       g_upper_level,
         " | Lower: ",       g_lower_level,
         " | SL dist: ",     g_stop_distance,
         " | TP dist: ",     g_tp_distance,
         " | RR: ",          RR_Ratio);
}

//+------------------------------------------------------------------+
//| Direction to String                                               |
//+------------------------------------------------------------------+
string DirectionToString()
{
   switch(Trade_Direction)
   {
      case TRADE_BOTH:       return "Both";
      case TRADE_LONG_ONLY:  return "Long Only";
      case TRADE_SHORT_ONLY: return "Short Only";
      default:               return "Unknown";
   }
}
//+------------------------------------------------------------------+
