import React from 'react';
import { cn } from '../../lib/utils';
import { 
  Send, Upload, Image, Mic, MicOff, Paperclip, X, FileText,
  Loader2, Plus
} from 'lucide-react';
import { Button } from './Button';
import { Textarea, Label } from './Input';
import { Badge } from './Badge';
import { Card } from './Card';

export const MessageComposer = ({
  value,
  onChange,
  onSend,
  onFileUpload,
  onImageUpload,
  onVoiceToggle,
  isLoading = false,
  isRecording = false,
  uploadedFiles = [],
  uploadedImages = [],
  onRemoveFile,
  onRemoveImage,
  placeholder = "Type your message...",
  maxLength = 4000,
  className,
  ...props
}) => {
  const textareaRef = React.useRef(null);
  const fileInputRef = React.useRef(null);
  const imageInputRef = React.useRef(null);

  const [isDragging, setIsDragging] = React.useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (value.trim() && !isLoading && onSend) {
      onSend(value.trim());
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    
    const files = Array.from(e.dataTransfer.files);
    const imageFiles = files.filter(file => file.type.startsWith('image/'));
    const documentFiles = files.filter(file => !file.type.startsWith('image/'));
    
    if (imageFiles.length > 0 && onImageUpload) {
      onImageUpload(imageFiles);
    }
    if (documentFiles.length > 0 && onFileUpload) {
      onFileUpload(documentFiles);
    }
  };

  const canSend = value.trim() && !isLoading;
  const hasAttachments = uploadedFiles.length > 0 || uploadedImages.length > 0;

  return (
    <Card 
      variant="elevated"
      padding="default"
      className={cn(
        'sticky bottom-0 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60',
        isDragging && 'border-primary bg-primary/5',
        className
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      {...props}
    >
      {/* File Upload Overlay */}
      {isDragging && (
        <div className="absolute inset-0 bg-primary/10 border-2 border-dashed border-primary rounded-lg flex items-center justify-center z-10">
          <div className="text-center">
            <Upload className="w-8 h-8 text-primary mx-auto mb-2" />
            <p className="text-sm font-medium text-primary">Drop files to upload</p>
          </div>
        </div>
      )}

      {/* Uploaded Files Preview */}
      {hasAttachments && (
        <div className="mb-4 space-y-2">
          {/* Document Files */}
          {uploadedFiles.length > 0 && (
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Attached Documents</Label>
              <div className="flex flex-wrap gap-2">
                {uploadedFiles.map((file, index) => (
                  <Badge 
                    key={index}
                    variant="outline"
                    className="flex items-center gap-2 pr-1"
                  >
                    <FileText className="w-3 h-3" />
                    <span className="truncate max-w-32">{file.name}</span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => onRemoveFile?.(index)}
                      className="h-4 w-4 hover:bg-destructive/20 hover:text-destructive"
                    >
                      <X className="w-3 h-3" />
                    </Button>
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Image Files */}
          {uploadedImages.length > 0 && (
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Attached Images</Label>
              <div className="flex flex-wrap gap-2">
                {uploadedImages.map((image, index) => (
                  <div key={index} className="relative">
                    <img
                      src={image.preview}
                      alt={image.name}
                      className="w-16 h-16 object-cover rounded border"
                    />
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => onRemoveImage?.(index)}
                      className="absolute -top-1 -right-1 h-5 w-5 bg-destructive text-destructive-foreground hover:bg-destructive/80"
                    >
                      <X className="w-3 h-3" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Main Input Area */}
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex gap-3">
          {/* Text Input */}
          <div className="flex-1 relative">
            <Textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => onChange?.(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              className="min-h-[60px] max-h-32 resize-none pr-12"
              maxLength={maxLength}
              disabled={isLoading}
            />
            
            {/* Character Count */}
            <div className="absolute bottom-2 right-2 text-xs text-muted-foreground">
              {value.length}/{maxLength}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-col gap-2">
            {/* Send Button */}
            <Button
              type="submit"
              variant="brand"
              size="icon"
              disabled={!canSend}
              loading={isLoading}
              className="h-[60px] w-12"
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </Button>
          </div>
        </div>

        {/* Bottom Toolbar */}
        <div className="flex items-center justify-between">
          {/* Left: Attachment Buttons */}
          <div className="flex items-center gap-1">
            {/* File Upload */}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading}
            >
              <Paperclip className="w-4 h-4 mr-1" />
              Files
            </Button>

            {/* Image Upload */}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => imageInputRef.current?.click()}
              disabled={isLoading}
            >
              <Image className="w-4 h-4 mr-1" />
              Images
            </Button>

            {/* Voice Recording */}
            <Button
              type="button"
              variant={isRecording ? "danger" : "ghost"}
              size="sm"
              onClick={onVoiceToggle}
              disabled={isLoading}
            >
              {isRecording ? (
                <MicOff className="w-4 h-4 mr-1" />
              ) : (
                <Mic className="w-4 h-4 mr-1" />
              )}
              {isRecording ? 'Stop' : 'Voice'}
            </Button>
          </div>

          {/* Right: Hints */}
          <div className="hidden sm:flex items-center text-xs text-muted-foreground space-x-4">
            <span>Press Enter to send</span>
            <span>Shift+Enter for new line</span>
          </div>
        </div>
      </form>

      {/* Hidden File Inputs */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.csv,.xlsx,.txt,.docx"
        onChange={(e) => onFileUpload?.(Array.from(e.target.files))}
        className="hidden"
      />
      <input
        ref={imageInputRef}
        type="file"
        multiple
        accept="image/*"
        onChange={(e) => onImageUpload?.(Array.from(e.target.files))}
        className="hidden"
      />
    </Card>
  );
};
