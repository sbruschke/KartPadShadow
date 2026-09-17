#import "KartPadDiscExtractor.h"

#include <algorithm>
#include <atomic>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>

#include "DiscIO/DiscExtractor.h"
#include "DiscIO/Filesystem.h"
#include "DiscIO/Volume.h"

namespace fs = std::filesystem;

namespace {

NSError *KartPadExtractionError(NSInteger code, NSString *message) {
  return [NSError errorWithDomain:@"dev.kartpad.disc-extraction"
                             code:code
                         userInfo:@{NSLocalizedDescriptionKey : message}];
}

void KartPadReportExtractionProgress(KartPadDiscExtractionProgress progress,
                                    NSString *status, double fraction) {
  if (progress == nil) return;
  dispatch_async(dispatch_get_main_queue(), ^{
    progress(status, std::clamp(fraction, 0.0, 1.0));
  });
}

}  // namespace

@implementation KartPadDiscExtractor

+ (BOOL)extractImageAtPath:(NSString *)imagePath
               toDirectory:(NSString *)destination
                   progress:(KartPadDiscExtractionProgress)progress
                      error:(NSError **)error {
  KartPadReportExtractionProgress(progress, @"Opening disc image", 0.0);
  std::unique_ptr<DiscIO::Volume> volume =
      DiscIO::CreateVolume(imagePath.fileSystemRepresentation);
  if (!volume) {
    if (error != nullptr) {
      *error = KartPadExtractionError(1, @"Dolphin could not open the disc image.");
    }
    return NO;
  }

  const DiscIO::Partition partition = volume->GetGamePartition();
  const DiscIO::FileSystem *filesystem = volume->GetFileSystem(partition);
  if (!filesystem || !filesystem->IsValid()) {
    if (error != nullptr) {
      *error = KartPadExtractionError(2, @"Dolphin could not read the game filesystem.");
    }
    return NO;
  }

  const std::string gameID = volume->GetGameID(partition);
  const std::optional<u16> revision = volume->GetRevision(partition);
  if (gameID != "RMCE01" || revision != std::optional<u16>{0}) {
    if (error != nullptr) {
      *error = KartPadExtractionError(
          3, @"KartPad Shadow supports RMCE01 (NTSC-U), revision 0 only.");
    }
    return NO;
  }

  std::error_code filesystemError;
  const fs::path root = destination.fileSystemRepresentation;
  fs::create_directories(root / "files", filesystemError);
  if (filesystemError) {
    if (error != nullptr) {
      *error = KartPadExtractionError(4, @"Could not create the extraction directory.");
    }
    return NO;
  }

  KartPadReportExtractionProgress(progress, @"Extracting system data", 0.05);
  if (!DiscIO::ExportSystemData(*volume, partition, root.string())) {
    if (error != nullptr) {
      *error = KartPadExtractionError(5, @"System-data extraction failed.");
    }
    return NO;
  }

  const u64 total = std::max<u64>(1, filesystem->GetRoot().GetTotalChildren());
  std::atomic<u64> completed{0};
  KartPadReportExtractionProgress(progress, @"Extracting game files", 0.10);
  DiscIO::ExportDirectory(
      *volume, partition, filesystem->GetRoot(), true, "", (root / "files").string(),
      [&completed, total, progress](const std::string &path) {
        const u64 current = ++completed;
        if (progress != nil && (current == total || current % 16 == 0)) {
          const double fraction = 0.10 + 0.85 *
              static_cast<double>(current) / static_cast<double>(total);
          NSString *status = path.empty() ? @"Extracting game files" : @(path.c_str());
          KartPadReportExtractionProgress(progress, status, fraction);
        }
        return false;
      });

  if (completed.load() != total ||
      !fs::exists(root / "files" / "rel" / "StaticR.rel")) {
    if (error != nullptr) {
      *error = KartPadExtractionError(6, @"Game-file extraction was incomplete.");
    }
    return NO;
  }

  KartPadReportExtractionProgress(progress, @"Validating extracted game data", 0.98);
  return YES;
}

@end
