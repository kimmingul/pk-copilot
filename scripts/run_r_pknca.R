#!/usr/bin/env Rscript
# run_r_pknca.R — pk-copilot PKNCA cross-validation backend
#
# Usage:
#   Rscript run_r_pknca.R \
#     --input   <concentration_csv> \
#     --output  <output_csv> \
#     [--dose   <dose_csv>] \
#     [--auc-method "linear up log down"]
#
# Output CSV columns: subject_id, parameter, value, unit
#
# Exit codes:
#   0 — success
#   1 — runtime error
#   2 — PKNCA package not available

suppressPackageStartupMessages({
  if (!requireNamespace("PKNCA", quietly = TRUE)) {
    message("ERROR: PKNCA package is not installed.")
    message("Install with: install.packages('PKNCA')")
    quit(status = 2, save = "no")
  }
})

library(PKNCA)

# ---------------------------------------------------------------------------
# Argument parsing (lightweight — no argparse dependency)
# ---------------------------------------------------------------------------

parse_args <- function(argv) {
  args <- list(
    input     = NULL,
    dose      = NULL,
    output    = NULL,
    auc_method = "linear up log down"
  )
  i <- 1L
  while (i <= length(argv)) {
    flag <- argv[[i]]
    if (flag == "--input" && i < length(argv)) {
      args$input <- argv[[i + 1L]]
      i <- i + 2L
    } else if (flag == "--dose" && i < length(argv)) {
      args$dose <- argv[[i + 1L]]
      i <- i + 2L
    } else if (flag == "--output" && i < length(argv)) {
      args$output <- argv[[i + 1L]]
      i <- i + 2L
    } else if (flag == "--auc-method" && i < length(argv)) {
      args$auc_method <- argv[[i + 1L]]
      i <- i + 2L
    } else {
      i <- i + 1L
    }
  }
  args
}

args <- parse_args(commandArgs(trailingOnly = TRUE))

if (is.null(args$input)) {
  message("ERROR: --input is required")
  quit(status = 1, save = "no")
}
if (is.null(args$output)) {
  message("ERROR: --output is required")
  quit(status = 1, save = "no")
}

if (!file.exists(args$input)) {
  message(paste0("ERROR: input file not found: ", args$input))
  quit(status = 1, save = "no")
}

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

tryCatch({
  conc_df <- read.csv(args$input, stringsAsFactors = FALSE)
}, error = function(e) {
  message(paste0("ERROR reading input CSV: ", e$message))
  quit(status = 1, save = "no")
})

# Normalise column names to lowercase
names(conc_df) <- tolower(names(conc_df))

# Expect columns: subject_id (or subject), time, concentration (or conc)
if (!"subject_id" %in% names(conc_df) && "subject" %in% names(conc_df)) {
  conc_df$subject_id <- conc_df$subject
}
if (!"concentration" %in% names(conc_df) && "conc" %in% names(conc_df)) {
  conc_df$concentration <- conc_df$conc
}

required_cols <- c("subject_id", "time", "concentration")
missing_cols <- setdiff(required_cols, names(conc_df))
if (length(missing_cols) > 0) {
  message(paste0("ERROR: missing columns in input CSV: ",
                 paste(missing_cols, collapse = ", ")))
  quit(status = 1, save = "no")
}

# Dose data
dose_amount <- 1.0  # default when no dose file supplied
if (!is.null(args$dose) && file.exists(args$dose)) {
  dose_df <- read.csv(args$dose, stringsAsFactors = FALSE)
  names(dose_df) <- tolower(names(dose_df))
  if ("amount" %in% names(dose_df)) {
    dose_amount <- as.numeric(dose_df$amount[[1]])
  } else if ("dose" %in% names(dose_df)) {
    dose_amount <- as.numeric(dose_df$dose[[1]])
  }
} else if ("dose" %in% names(conc_df)) {
  # Inline dose column in concentration file
  dose_vals <- conc_df$dose[!is.na(conc_df$dose)]
  if (length(dose_vals) > 0) {
    dose_amount <- as.numeric(dose_vals[[1]])
  }
}

# ---------------------------------------------------------------------------
# PKNCA parameter name → pk-copilot canonical name map
# ---------------------------------------------------------------------------

pknca_to_canonical <- c(
  "cmax"                   = "Cmax",
  "tmax"                   = "Tmax",
  "tlast"                  = "Tlast",
  "clast.obs"              = "Clast",
  "auclast"                = "AUClast",
  "aucall"                 = "AUClast",
  "aucinf.obs"             = "AUCINF_obs",
  "aucinf.pred"            = "AUCINF_pred",
  "lambda.z"               = "Lambda_z",
  "half.life"              = "HL_Lambda_z",
  "r.squared"              = "Rsq",
  "r.squared.adjusted"     = "Rsq_adjusted",
  "adj.r.squared"          = "Rsq_adjusted",
  "span.ratio"             = "Span_ratio",
  "lambda.z.n.points"      = "No_points_lambda_z",
  "lambda.z.time.first"    = "Lambda_z_lower",
  "lambda.z.time.last"     = "Lambda_z_upper",
  "mrt.obs"                = "MRTINF_obs",
  "mrtinf.obs"             = "MRTINF_obs",
  "mrt.pred"               = "MRTINF_pred",
  "mrtinf.pred"            = "MRTINF_pred",
  "cl.obs"                 = "CL_F",
  "cl.f.obs"               = "CL_F",
  "cl.pred"                = "CL_F",
  "vz.obs"                 = "Vz_F",
  "vz.f.obs"               = "Vz_F",
  "vz.pred"                = "Vz_F",
  "aumc.obs"               = "AUMCINF_obs",
  "aumcinf.obs"            = "AUMCINF_obs",
  "auclast.iv"             = "AUClast",
  "c0"                     = "C0"
)

# ---------------------------------------------------------------------------
# Run PKNCA for each subject
# ---------------------------------------------------------------------------

subjects <- unique(conc_df$subject_id)
out_rows <- list()

for (sid in subjects) {
  sub <- conc_df[conc_df$subject_id == sid, ]
  sub <- sub[order(sub$time), ]

  # Remove NA concentrations
  sub <- sub[!is.na(sub$concentration), ]
  if (nrow(sub) == 0L) next

  tryCatch({
    # Build PKconc and PKdose objects
    pk_conc <- PKNCAconc(sub, concentration ~ time | subject_id)

    # Build dose data frame for this subject
    dose_row <- data.frame(
      subject_id = sid,
      time       = 0,
      dose       = dose_amount,
      stringsAsFactors = FALSE
    )
    pk_dose <- PKNCAdose(dose_row, dose ~ time | subject_id)

    pk_data <- PKNCAdata(pk_conc, pk_dose)

    # Override AUC method if specified
    # PKNCA uses "lin up/log down" (default) or "linear" etc.
    # Map our canonical string to PKNCA's method parameter
    auc_method_str <- tolower(args$auc_method)
    if (grepl("log", auc_method_str)) {
      pk_data$options$auc.method <- "lin up/log down"
    } else {
      pk_data$options$auc.method <- "linear"
    }

    result <- pk.nca(pk_data)
    res_df <- as.data.frame(result$result)

    # Canonicalise PKNCA parameter names
    res_df$PPTESTCD_lower <- tolower(as.character(res_df$PPTESTCD))
    res_df$canonical <- pknca_to_canonical[res_df$PPTESTCD_lower]

    # Keep only rows we have a canonical mapping for
    res_df <- res_df[!is.na(res_df$canonical), ]

    for (j in seq_len(nrow(res_df))) {
      canon_name <- res_df$canonical[[j]]
      val        <- as.numeric(res_df$PPORRES[[j]])
      out_rows[[length(out_rows) + 1L]] <- data.frame(
        subject_id = as.character(sid),
        parameter  = canon_name,
        value      = val,
        unit       = "",
        stringsAsFactors = FALSE
      )
    }
  }, error = function(e) {
    message(paste0("WARNING: PKNCA failed for subject ", sid, ": ", e$message))
  })
}

# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------

if (length(out_rows) == 0L) {
  message("WARNING: no results produced by PKNCA")
  out_df <- data.frame(
    subject_id = character(0),
    parameter  = character(0),
    value      = numeric(0),
    unit       = character(0),
    stringsAsFactors = FALSE
  )
} else {
  out_df <- do.call(rbind, out_rows)
}

# Ensure output directory exists
out_dir <- dirname(args$output)
if (!dir.exists(out_dir)) {
  dir.create(out_dir, recursive = TRUE)
}

write.csv(out_df, args$output, row.names = FALSE)
cat(paste0("PKNCA: wrote ", nrow(out_df), " rows to ", args$output, "\n"))
quit(status = 0, save = "no")
