#!/usr/bin/env Rscript
# run_r_noncompart.R — pk-copilot NonCompart cross-validation backend
#
# Usage:
#   Rscript run_r_noncompart.R \
#     --input   <concentration_csv> \
#     --output  <output_csv> \
#     [--dose   <dose_csv>]
#
# Output CSV columns: subject_id, parameter, value, unit
#
# Exit codes:
#   0 — success
#   1 — runtime error
#   2 — NonCompart package not available

suppressPackageStartupMessages({
  if (!requireNamespace("NonCompart", quietly = TRUE)) {
    message("ERROR: NonCompart package is not installed.")
    message("Install with: install.packages('NonCompart')")
    quit(status = 2, save = "no")
  }
})

library(NonCompart)

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

parse_args <- function(argv) {
  args <- list(
    input  = NULL,
    dose   = NULL,
    output = NULL
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

names(conc_df) <- tolower(names(conc_df))

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

# Dose amount
dose_amount <- 1.0
if (!is.null(args$dose) && file.exists(args$dose)) {
  dose_df <- read.csv(args$dose, stringsAsFactors = FALSE)
  names(dose_df) <- tolower(names(dose_df))
  if ("amount" %in% names(dose_df)) {
    dose_amount <- as.numeric(dose_df$amount[[1]])
  } else if ("dose" %in% names(dose_df)) {
    dose_amount <- as.numeric(dose_df$dose[[1]])
  }
} else if ("dose" %in% names(conc_df)) {
  dose_vals <- conc_df$dose[!is.na(conc_df$dose)]
  if (length(dose_vals) > 0) {
    dose_amount <- as.numeric(dose_vals[[1]])
  }
}

# ---------------------------------------------------------------------------
# NonCompart parameter name → pk-copilot canonical name map
# ---------------------------------------------------------------------------

nc_to_canonical <- c(
  "CMAX"        = "Cmax",
  "TMAX"        = "Tmax",
  "TLST"        = "Tlast",
  "CLST"        = "Clast",
  "AUCLST"      = "AUClast",
  "AUCIFO"      = "AUCINF_obs",
  "AUCIFP"      = "AUCINF_pred",
  "LAMZHL"      = "HL_Lambda_z",
  "LAMZ"        = "Lambda_z",
  "LAMZLL"      = "Lambda_z_lower",
  "LAMZUL"      = "Lambda_z_upper",
  "LAMZNPT"     = "No_points_lambda_z",
  "R2ADJ"       = "Rsq_adjusted",
  "CORRXY"      = "Rsq",
  "MRTEVLST"    = "MRTINF_obs",
  "MRTEVIFO"    = "MRTINF_obs",
  "MRTEVIFP"    = "MRTINF_pred",
  "CLFO"        = "CL_F",
  "CLFP"        = "CL_F",
  "VZO"         = "Vz_F",
  "VZP"         = "Vz_F",
  "SPANR"       = "Span_ratio",
  "C0"          = "C0"
)

# ---------------------------------------------------------------------------
# Run NonCompart for each subject
# ---------------------------------------------------------------------------

subjects <- unique(conc_df$subject_id)
out_rows <- list()

for (sid in subjects) {
  sub <- conc_df[conc_df$subject_id == sid, ]
  sub <- sub[order(sub$time), ]
  sub <- sub[!is.na(sub$concentration), ]
  if (nrow(sub) == 0L) next

  tryCatch({
    # tblNCA expects: numeric time vector, numeric conc vector, dose
    times  <- as.numeric(sub$time)
    concs  <- as.numeric(sub$concentration)

    # NonCompart >= 0.5: sNCA() for single-subject
    nca_result <- sNCA(
      x    = times,
      y    = concs,
      dose = dose_amount,
      adm  = "Extravascular",    # oral / extravascular
      method = 2                 # 1=linear, 2=linear-up/log-down
    )

    # sNCA returns a named numeric vector
    for (pname in names(nca_result)) {
      canon_name <- nc_to_canonical[pname]
      if (is.na(canon_name)) next
      val <- as.numeric(nca_result[[pname]])
      if (is.na(val)) next
      out_rows[[length(out_rows) + 1L]] <- data.frame(
        subject_id = as.character(sid),
        parameter  = canon_name,
        value      = val,
        unit       = "",
        stringsAsFactors = FALSE
      )
    }
  }, error = function(e) {
    message(paste0("WARNING: NonCompart failed for subject ", sid, ": ", e$message))
  })
}

# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------

if (length(out_rows) == 0L) {
  message("WARNING: no results produced by NonCompart")
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

out_dir <- dirname(args$output)
if (!dir.exists(out_dir)) {
  dir.create(out_dir, recursive = TRUE)
}

write.csv(out_df, args$output, row.names = FALSE)
cat(paste0("NonCompart: wrote ", nrow(out_df), " rows to ", args$output, "\n"))
quit(status = 0, save = "no")
